import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter-tight";
import "./styles.css";
import App from "./App";
import { registerSW } from "virtual:pwa-register";

// Mise à jour de l'app : vérifie une nouvelle version à l'ouverture, au retour sur l'app
// et toutes les 30 min ; si elle existe, elle s'installe et la page se recharge seule.
registerSW({
  immediate: true,
  onRegisteredSW(_url, reg) {
    if (!reg) return;
    const check = () => reg.update().catch(() => undefined);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") check();
    });
    setInterval(check, 30 * 60 * 1000);
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
