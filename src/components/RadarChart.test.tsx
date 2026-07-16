// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { RadarChart } from "./RadarChart";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("RadarChart no-data handling", () => {
  it("does not draw a missing category as a zero-valued polygon point", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <RadarChart
            series={[
              {
                modelId: "partial",
                name: "Partial model",
                color: "#ffffff",
                points: [
                  { category: "knowledge", value: 0.5 },
                  { category: "reasoning", value: null },
                  { category: "math", value: 0.5 },
                  { category: "coding", value: 0.5 },
                  { category: "agentic", value: 0.5 },
                  { category: "instruction", value: 0.5 },
                  { category: "chat", value: 0.5 },
                  { category: "vision", value: 0.5 },
                ],
              },
            ]}
          />
        );
      });

      expect(container.querySelectorAll("polygon[stroke-width]")).toHaveLength(0);
      expect(container.textContent).toContain("Partial model: incomplete category data");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });
});
