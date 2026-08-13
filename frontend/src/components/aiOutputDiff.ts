export interface AiDiffRow {
  kind: 'context' | 'add' | 'remove'
  oldLine?: string
  newLine?: string
  text: string
}

/** Turns a unified diff into the bounded rows used by the output preview. */
export function aiDiffRows(diff: string): AiDiffRow[] {
  let oldLine = 0
  let newLine = 0
  const rows: AiDiffRow[] = []
  for (const line of diff.split('\n')) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line)
    if (hunk) {
      oldLine = Number(hunk[1])
      newLine = Number(hunk[2])
      continue
    }
    if (
      line.startsWith('+++')
      || line.startsWith('---')
      || line.startsWith('diff ')
      || line.startsWith('index ')
      || line.startsWith('new file mode ')
      || line.startsWith('deleted file mode ')
      || line.startsWith('similarity index ')
      || line.startsWith('rename from ')
      || line.startsWith('rename to ')
      || line.startsWith('\\ No newline at end of file')
    ) continue
    if (line.startsWith('+')) rows.push({ kind: 'add', newLine: String(newLine++), text: line.slice(1) })
    else if (line.startsWith('-')) rows.push({ kind: 'remove', oldLine: String(oldLine++), text: line.slice(1) })
    else rows.push({ kind: 'context', oldLine: oldLine ? String(oldLine++) : '', newLine: newLine ? String(newLine++) : '', text: line })
  }
  return rows.slice(0, 80)
}
