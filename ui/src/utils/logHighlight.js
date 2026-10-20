/* 控制台行高亮规则（对齐 runner 日志格式；LogViewer 与 ConsoleStream 共用） */
export function lineClass(line) {
  if (/ui_automation\.step:.*\bPASS\b|\bPASS\s+\S+\s*\|/.test(line)) return "ln-pass";
  if (/ui_automation\.step:.*\bFAIL\b|\bFAIL\s+\S+\s*\|/.test(line)) return "ln-fail";
  if (/ui_automation\.step:.*\bSTART\b|\bSTART\s+\S+\s*\|/.test(line)) return "ln-step";
  if (/Saved (pass|fail) screenshot/i.test(line)) return "ln-shot";
  if (/===\s*Step\d+/i.test(line)) return "ln-head";
  if (/\[ERROR\]|Traceback|Exception:/.test(line)) return "ln-err";
  if (/^=====\s.+CASE|^RESULT\b|^CASE\b/.test(line)) return "ln-head";
  return "";
}
