/* SSE 控制台流组合式函数。
 * 协议（app/api/sse_routes.py）：snapshot / append(id=字节偏移) / reset / end。
 * 断线由 EventSource 自动重连（携带 Last-Event-ID 续传，服务端不发重复
 * snapshot）；文件被清理时服务端先发 reset 再补 snapshot。
 *
 * 用法：const stream = createConsoleStream(); stream.open(loopId);
 * 切换页签不影响流——只有绑定新 loop 才 close 旧的。
 */
import { ref } from "vue";

export function createConsoleStream() {  const text = ref("");
  const state = ref("idle");     // idle | connecting | open | end
  const endStatus = ref("");
  const loopId = ref("");
  let es = null;

  function open(id) {
    if (loopId.value === id && es) return;  // 已在该 loop 的流上
    close();
    loopId.value = id;
    state.value = "connecting";
    es = new EventSource(`/api/loops/${encodeURIComponent(id)}/console`);

    es.addEventListener("snapshot", (e) => {
      try { text.value = JSON.parse(e.data).text || ""; } catch { text.value = ""; }
      state.value = "open";
    });
    es.addEventListener("append", (e) => {
      // SSE 规范把多行 data 以 \n 重组；tail 块按行切分，缺尾换行则补
      text.value += e.data.endsWith("\n") ? e.data : e.data + "\n";
      if (state.value !== "open") state.value = "open";
    });
    es.addEventListener("reset", () => { text.value = ""; });
    es.addEventListener("end", (e) => {
      try { endStatus.value = JSON.parse(e.data).status || ""; } catch { endStatus.value = ""; }
      state.value = "end";
      es?.close();
      es = null;
    });
    es.onerror = () => {
      // EventSource 自动重连（服务端按 Last-Event-ID 续传）；若浏览器放弃
      // 连接（readyState=CLOSED）则标记结束，避免无限转圈
      if (es && es.readyState === EventSource.CLOSED) state.value = "end";
    };
  }

  function close() {
    es?.close();
    es = null;
    text.value = "";
    state.value = "idle";
    endStatus.value = "";
    loopId.value = "";
  }

  return { text, state, endStatus, loopId, open, close };
}

/* 应用级单例：运行台 store 与组件共享同一条流 */
export const consoleStream = createConsoleStream();
