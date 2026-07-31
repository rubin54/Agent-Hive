import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { CatalogPage } from "./features/catalog/CatalogPage";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Der Katalog ändert sich nur beim expliziten Sync — kein Grund für Refetches
      // beim Fensterwechsel.
      refetchOnWindowFocus: false,
      staleTime: 5 * 60 * 1000,
      retry: 1,
    },
  },
});

const container = document.getElementById("root");
if (!container) throw new Error("#root fehlt im index.html");

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <CatalogPage />
    </QueryClientProvider>
  </StrictMode>,
);
