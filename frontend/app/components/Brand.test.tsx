import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Brand } from "@/app/components/Brand";

describe("Brand", () => {
  it("отображает бренд рабочего места оператора", () => {
    render(<Brand />);
    expect(screen.getByText(/kb-support/i)).toBeInTheDocument();
    expect(screen.getByText(/оператор/i)).toBeInTheDocument();
  });
});
