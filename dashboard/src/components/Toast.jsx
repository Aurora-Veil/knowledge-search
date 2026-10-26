import { createContext, useCallback, useContext, useRef, useState } from "react";

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const seq = useRef(0);

  const dismiss = useCallback((id) => {
    setToasts((list) => list.filter((item) => item.id !== id));
  }, []);

  const showToast = useCallback(
    (text, type = "success") => {
      seq.current += 1;
      const id = seq.current;
      setToasts((list) => [...list, { id, text, type }]);
      setTimeout(() => dismiss(id), 3000);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}

      <div className="toast-stack" aria-live="polite">
        {toasts.map((item) => (
          <div
            key={item.id}
            className={`toast toast-${item.type}`}
            role="status"
            onClick={() => dismiss(item.id)}
          >
            {item.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast 必须在 ToastProvider 里面使用");
  }
  return context;
}
