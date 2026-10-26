import { useCallback, useEffect, useRef, useState } from "react";

const PROBE_TIMEOUT_MS = 4000;

const INITIAL = {
  state: "idle",
  label: "尚未检测",
  detail: "打开菜单后检测 MCP 连接。",
};

function classify(status) {
  if (status === 401 || status === 403) {
    return {
      state: "down",
      label: "MCP 需要鉴权",
      detail: "端点有响应，但当前请求没有权限。",
    };
  }

  if (status === 404) {
    return {
      state: "down",
      label: "MCP 未挂载",
      detail: "没有找到 /mcp 端点，确认后端已启动并挂载了 MCP。",
    };
  }

  if (status >= 500) {
    return {
      state: "down",
      label: "MCP 异常",
      detail: `返回 HTTP ${status}。`,
    };
  }

  if (status === 200 || status === 400 || status === 405 || status === 406) {
    return {
      state: "up",
      label: "MCP 可连接",
      detail: `端点可达（HTTP ${status}）。`,
    };
  }

  return {
    state: "up",
    label: "MCP 可连接",
    detail: `端点有响应（HTTP ${status}）。`,
  };
}

export function useMcpStatus() {
  const [status, setStatus] = useState(INITIAL);
  const controllerRef = useRef(null);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      controllerRef.current?.abort();
    };
  }, []);

  const check = useCallback(async () => {
    controllerRef.current?.abort();

    const controller = new AbortController();
    controllerRef.current = controller;

    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, PROBE_TIMEOUT_MS);

    setStatus({
      state: "checking",
      label: "正在检测 MCP…",
      detail: "正在请求 /mcp 端点。",
    });

    try {
      const res = await fetch("/mcp", {
        method: "GET",
        headers: { Accept: "text/event-stream" },
        signal: controller.signal,
      });

      if (res.body) {
        res.body.cancel().catch(() => {});
      }

      if (!aliveRef.current) return;
      setStatus(classify(res.status));
    } catch {
      if (!aliveRef.current) return;
      if (controller.signal.aborted && !timedOut) return;

      setStatus({
        state: "down",
        label: timedOut ? "MCP 检测超时" : "MCP 连接失败",
        detail: timedOut
          ? `超过 ${PROBE_TIMEOUT_MS / 1000} 秒没有响应。`
          : "无法连接 MCP 服务，确认后端已启动。",
      });
    } finally {
      clearTimeout(timer);
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    }
  }, []);

  return { ...status, check };
}
