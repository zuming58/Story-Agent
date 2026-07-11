import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import { App } from "./App";

describe("Story Agent shell", () => {
  it("keeps the Agent panel while navigating between modules", async () => {
    const user = userEvent.setup();
    render(<TooltipProvider><MemoryRouter initialEntries={["/planning"]}><App /></MemoryRouter></TooltipProvider>);

    expect(screen.getByRole("heading", { name: "故事规划中心" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "故事 Agent" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /Canon/ }));
    expect(screen.getByRole("heading", { name: "Canon 设定库" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "故事 Agent" })).toBeInTheDocument();
  });
});
