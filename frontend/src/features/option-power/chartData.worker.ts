import { normalizeChartData, type ChartDataInput } from "./chartData";

type NormalizeRequest = {
  type: "normalize";
  requestId: number;
  payload: ChartDataInput;
};

self.onmessage = (event: MessageEvent<NormalizeRequest>) => {
  if (event.data.type !== "normalize") {
    return;
  }
  self.postMessage({
    type: "normalized",
    requestId: event.data.requestId,
    payload: normalizeChartData(event.data.payload),
  });
};
