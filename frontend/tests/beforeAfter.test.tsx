import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BeforeAfter, HERO_ROWS } from "@/components/site/BeforeAfter";

describe("hero before/after", () => {
  it("lists each pair in reading order, with the source id it cites", () => {
    render(<BeforeAfter />);
    const figure = screen.getByRole("figure", { name: /Sample data/ });
    const items = within(figure).getAllByRole("listitem");
    expect(items).toHaveLength(HERO_ROWS.length);
    HERO_ROWS.forEach((row, i) => {
      expect(items[i]).toHaveTextContent(`Before: ${row.before}`);
      expect(items[i]).toHaveTextContent(`cites ${row.id}): ${row.after}`);
    });
    // Status comes as a word, not only colour.
    expect(within(figure).getByText(/Verified: every line traces to your resume/)).toBeInTheDocument();
  });

  it("keeps every number in the tailored lines from the original (demo data obeys the verifier rule)", () => {
    for (const row of HERO_ROWS) {
      const nums = (t: string) => (t.match(/\d+/g) ?? []).sort();
      expect(nums(row.after)).toEqual(nums(row.before));
    }
  });
});
