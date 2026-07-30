"""并发工具调用下的 HtmlEditSession 写入安全。

LangGraph 的 ToolNode 用 asyncio.gather 并发执行同一条助手消息里的多个 tool
call；同步工具会被 LangChain 下放到线程池，因此这些方法是真并发调用的。这些
用例锁定两条不变量：并发补丁绝不静默丢失编辑，内联图片占位符表绝不错配。
"""
from __future__ import annotations

import asyncio
import threading
import unittest

from app.services.chat_agent import HtmlEditSession
from app.services.html_workspace import WorkspaceError


def _block_ids_by_text(session: HtmlEditSession, *texts: str) -> dict[str, str]:
    """按正文定位块 id。

    这里走 search 而不是 document_map：地图会截断到 MAX_MAP_BLOCKS，长文档尾部
    的块不会出现在地图里。search 也正是 Agent 定位块的实际路径。
    """
    found: dict[str, str] = {}
    for text in texts:
        for block in session.search(text)["results"]:
            if block["tag"] == "p" and block["text"].strip() == text:
                found[text] = block["block_id"]
                break
    return found


class ConcurrentPatchTests(unittest.TestCase):
    def test_concurrent_patches_never_silently_lose_an_edit(self) -> None:
        # 体量接近真实公众号文章：workspace() 要重新解析整篇 HTML，
        # 这段耗时曾把无锁 read-modify-write 的竞态窗口开得很大。
        filler = "".join(f"<p>段落内容 {index} 用于撑大文档体量</p>" for index in range(400))
        source = f"<section><p>AAA</p>{filler}<p>BBB</p></section>"

        for _ in range(8):
            session = HtmlEditSession(source)
            ids = _block_ids_by_text(session, "AAA", "BBB")
            self.assertEqual(len(ids), 2)
            revision = session.document_map()["revision"]
            hashes = {
                block["block_id"]: block["expected_hash"]
                for block in session.read_blocks([ids["AAA"], ids["BBB"]])["blocks"]
            }

            def patch(text: str, replacement: str) -> str:
                try:
                    session.patch_blocks(
                        revision,
                        [
                            {
                                "block_id": ids[text],
                                "expected_hash": hashes[ids[text]],
                                "mode": "replace_inner",
                                "html": replacement,
                            }
                        ],
                    )
                except WorkspaceError:
                    return "rejected"
                return "applied"

            async def run_both() -> list[str]:
                return list(
                    await asyncio.gather(
                        asyncio.to_thread(patch, "AAA", "FIRST-EDIT"),
                        asyncio.to_thread(patch, "BBB", "SECOND-EDIT"),
                    )
                )

            outcomes = asyncio.run(run_both())
            applied = [
                marker for marker in ("FIRST-EDIT", "SECOND-EDIT") if marker in session.html
            ]

            # 关键不变量：报告成功的编辑必须真实存在于文档中。
            # 无锁实现下两个补丁都返回成功，却只有一处生效。
            self.assertEqual(
                outcomes.count("applied"),
                len(applied),
                f"报告成功 {outcomes.count('applied')} 处，实际生效 {len(applied)} 处",
            )
            self.assertGreaterEqual(len(applied), 1)

    def test_second_concurrent_patch_fails_with_a_recoverable_error(self) -> None:
        """被拒绝的一方必须收到可恢复的 revision 冲突提示，而不是静默成功。"""
        session = HtmlEditSession("<section><p>AAA</p><p>BBB</p></section>")
        ids = _block_ids_by_text(session, "AAA", "BBB")
        revision = session.document_map()["revision"]
        hashes = {
            block["block_id"]: block["expected_hash"]
            for block in session.read_blocks([ids["AAA"], ids["BBB"]])["blocks"]
        }
        both_snapshotted = threading.Barrier(2, timeout=5)
        errors: list[str] = []

        def patch(text: str, replacement: str) -> str:
            operations = [
                {
                    "block_id": ids[text],
                    "expected_hash": hashes[ids[text]],
                    "mode": "replace_inner",
                    "html": replacement,
                }
            ]
            both_snapshotted.wait()
            try:
                session.patch_blocks(revision, operations)
            except WorkspaceError as exc:
                errors.append(str(exc))
                return "rejected"
            return "applied"

        async def run_both() -> list[str]:
            return list(
                await asyncio.gather(
                    asyncio.to_thread(patch, "AAA", "FIRST-EDIT"),
                    asyncio.to_thread(patch, "BBB", "SECOND-EDIT"),
                )
            )

        outcomes = asyncio.run(run_both())
        self.assertEqual(sorted(outcomes), ["applied", "rejected"])
        self.assertEqual(len(errors), 1)
        self.assertIn("文档已变化", errors[0])

    def test_concurrent_reads_assign_one_placeholder_per_inline_image(self) -> None:
        """并发只读工具不得让两张图片映射到同一个占位符。

        注意这是不变量检查，不是竞态复现。占位符分配的 check-then-set 窗口只有
        几条字节码，实测在 CPython 下即使 12 线程加屏障、switchinterval 调到
        1e-9 也无法自然触发（0/200）；只有在窗口里人为插入 sleep 才能稳定复现
        （无锁 10/10 损坏，加锁 0/10）。因此该用例的作用是锁定「并发读后占位符
        表始终自洽」，而非证明锁的必要性 —— 后者由上面两个补丁用例保证。
        """
        images = [f"data:image/png;base64,{chr(65 + index) * 300}" for index in range(6)]
        source = "<section>" + "".join(f'<p><img src="{value}"></p>' for value in images) + "</section>"
        session = HtmlEditSession(source)

        async def read_all() -> None:
            await asyncio.gather(*(asyncio.to_thread(session.document_map) for _ in range(6)))

        asyncio.run(read_all())

        tokens = session._inline_data_tokens
        self.assertEqual(len(tokens), len(images))
        # 每张原图一个唯一占位符，且反查表可无损还原全部原图。
        self.assertEqual(len(set(tokens.values())), len(images))
        self.assertEqual(len(session._inline_data_by_token), len(images))
        restored = session._restore_inline_data_tokens("".join(tokens.values()))
        for value in images:
            self.assertIn(value, restored)


if __name__ == "__main__":
    unittest.main()
