"""临时脚本：一个极简的 OpenAI 兼容 /chat/completions 流式模拟服务器，用于在没有真实
API Key 的情况下，端到端验证 OpenAICompatibleClient 的 SSE 解析逻辑与完整 Agent 循环。
根据工具结果数量，依次返回：
  第1轮 -> 调用 view_html 读取第 1-2 行
  第2轮 -> 调用 str_replace_html 把 <h1>旧标题</h1> 改成新标题
  第3轮 -> 调用 check_compliance
  第4轮 -> 纯文本收尾，不再调用工具
"""
import json

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()


def _sse_chunk(obj) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _make_tool_call_stream(call_id: str, name: str, arguments: str, lead_text: str):
    async def gen():
        yield _sse_chunk({"choices": [{"delta": {"content": lead_text}, "finish_reason": None}]})
        yield _sse_chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "id": call_id, "function": {"name": name, "arguments": ""}}
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
        )
        # 模拟参数按字符切片增量返回（真实 OpenAI 流式协议的常见行为）
        for i in range(0, len(arguments), 8):
            piece = arguments[i : i + 8]
            yield _sse_chunk(
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}, "finish_reason": None}]}
            )
        yield _sse_chunk({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
        yield "data: [DONE]\n\n"

    return gen


def _make_final_text_stream(text: str):
    async def gen():
        for i in range(0, len(text), 6):
            yield _sse_chunk({"choices": [{"delta": {"content": text[i : i + 6]}, "finish_reason": None}]})
        yield _sse_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        yield "data: [DONE]\n\n"

    return gen


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    tool_result_count = sum(1 for m in messages if m.get("role") == "tool")

    if tool_result_count == 0:
        gen = _make_tool_call_stream(
            "call_1",
            "view_html",
            json.dumps({"start_line": 1, "end_line": 2}),
            "我先查看标题所在的源码行。",
        )
    elif tool_result_count == 1:
        gen = _make_tool_call_stream(
            "call_2",
            "str_replace_html",
            json.dumps({"old_str": "<h1>旧标题</h1>", "new_str": "<h1>Mock 服务器修改后的新标题</h1>"}, ensure_ascii=False),
            "好的，我先修改标题。",
        )
    elif tool_result_count == 2:
        gen = _make_tool_call_stream("call_3", "check_compliance", "{}", "现在做一次合规自检。")
    else:
        gen = _make_final_text_stream("已完成标题修改并通过合规自检，未发现严重问题，本轮编辑结束。")

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8098, log_level="warning")
