import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const downloadReportCsvAction = vi.fn();
vi.mock("./actions", () => ({
  downloadReportCsvAction: (...args: unknown[]) => downloadReportCsvAction(...args),
}));

import { ReportControls } from "./ReportControls";

describe("ReportControls", () => {
  beforeEach(() => {
    push.mockClear();
    downloadReportCsvAction.mockReset();
  });

  it("«Показать» с периодом → URL c type/from/to", () => {
    render(<ReportControls type="sla" from="2026-05-01" to="2026-05-31" />);
    fireEvent.click(screen.getByRole("button", { name: "Показать" }));
    expect(push).toHaveBeenCalledWith("/reports?type=sla&from=2026-05-01&to=2026-05-31");
  });

  it("«Показать» без периода → URL только с type (дефолт бэкенда)", () => {
    render(<ReportControls type="volume" />);
    fireEvent.click(screen.getByRole("button", { name: "Показать" }));
    expect(push).toHaveBeenCalledWith("/reports?type=volume");
  });

  it("«Скачать CSV»: server action → Blob + anchor download", async () => {
    downloadReportCsvAction.mockResolvedValue({ csv: "a,b\n1,2\n", filename: "report-volume.csv" });
    const createObjectURL = vi.fn(() => "blob:fake");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<ReportControls type="volume" />);
    fireEvent.click(screen.getByRole("button", { name: "Скачать CSV" }));

    await waitFor(() =>
      expect(downloadReportCsvAction).toHaveBeenCalledWith("volume", undefined, undefined),
    );
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    expect(click).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake");

    click.mockRestore();
    vi.unstubAllGlobals();
  });

  it("«Скачать CSV»: ошибка action → role=alert, без скачивания", async () => {
    downloadReportCsvAction.mockResolvedValue({ error: "Отчёты доступны только супервайзеру." });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<ReportControls type="operators" />);
    fireEvent.click(screen.getByRole("button", { name: "Скачать CSV" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Отчёты доступны только супервайзеру."),
    );
    expect(click).not.toHaveBeenCalled();
    click.mockRestore();
  });
});
