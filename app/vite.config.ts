import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  base: "./",
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: false,
      includeAssets: ["icons/*.png", "icons/*.svg"],
      manifest: {
        name: "Pronos NBA",
        short_name: "Pronos",
        lang: "fr",
        start_url: ".",
        display: "standalone",
        orientation: "portrait",
        background_color: "#F5F5F2",
        theme_color: "#F5F5F2",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,woff2,png,svg}"],
        runtimeCaching: [
          {
            urlPattern: /\/data\/.*\.json$/,
            handler: "NetworkFirst",
            options: { cacheName: "donnees", networkTimeoutSeconds: 4 },
          },
        ],
      },
    }),
  ],
});
