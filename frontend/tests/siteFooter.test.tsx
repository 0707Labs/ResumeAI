import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LEGAL_LINKS, SiteFooter } from "@/components/site/SiteFooter";

describe("site footer", () => {
  it("links every legal page, names who runs the product, and offers a grievance contact", () => {
    render(<SiteFooter />);
    const footer = screen.getByRole("contentinfo");
    const legal = within(footer).getByRole("navigation", { name: "Legal" });
    for (const { href, label } of LEGAL_LINKS) {
      expect(within(legal).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
    expect(footer).toHaveTextContent("A product of 0707Labs, MealOBox Foodtech Pvt Ltd");
    // Without a configured officer, the grievance page is the contact.
    expect(within(footer).getByRole("link", { name: "How to raise a concern" })).toHaveAttribute("href", "/legal/grievance");
  });
});
