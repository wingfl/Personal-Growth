import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

// 允许用 ?theme=dark 直接深链到暗色（截图、演示方便），与顶部开关共用同一份 localStorage
const themeParam = new URLSearchParams(window.location.search).get("theme");
if (themeParam === "dark" || themeParam === "light") {
  localStorage.setItem("theme", themeParam);
}
document.documentElement.classList.toggle("dark", localStorage.getItem("theme") === "dark");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
