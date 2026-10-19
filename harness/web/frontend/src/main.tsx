import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import "./styles.css";

// Тема до первого рендера: сохранённая или тёмная (как в макете).
document.documentElement.dataset.theme = localStorage.getItem("theme") || "dark";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
