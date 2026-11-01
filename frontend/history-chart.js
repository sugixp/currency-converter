// 30-day rate chart. Chart.js is loaded as a global from the CDN (see
// index.html); if it failed to load, the text summary still works.

const AMBER = "#ffb22e";
const MUTED = "#a4a9b1";
const GRID = "rgba(255, 255, 255, 0.06)";
const FONT_MONO =
  'ui-monospace, "Cascadia Mono", "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';

export function isChartAvailable() {
  return typeof window.Chart === "function";
}

export function createHistoryChart(canvas) {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const dayLabel = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  let pair = { from: "", to: "" };

  const chart = new window.Chart(canvas, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          data: [],
          borderColor: AMBER,
          borderWidth: 2.5,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: AMBER,
          // Monotone curves never overshoot the data, so the line never shows
          // a rate higher or lower than one that actually happened.
          cubicInterpolationMode: "monotone",
          fill: true,
          backgroundColor: (context) => {
            const { ctx, chartArea } = context.chart;
            if (!chartArea) return "transparent";
            const gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
            gradient.addColorStop(0, "rgba(255, 178, 46, 0.28)");
            gradient.addColorStop(1, "rgba(255, 178, 46, 0)");
            return gradient;
          },
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: reduceMotion ? false : { duration: 500 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#0b0c0e",
          borderColor: "#33373f",
          borderWidth: 1,
          titleColor: MUTED,
          bodyColor: "#ece8df",
          titleFont: { family: FONT_MONO },
          bodyFont: { family: FONT_MONO, size: 13, weight: "bold" },
          displayColors: false,
          callbacks: {
            label: (item) => `1 ${pair.from} = ${formatRate(item.parsed.y)} ${pair.to}`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { color: GRID },
          ticks: { color: MUTED, font: { family: FONT_MONO, size: 11 }, maxRotation: 0, autoSkipPadding: 16 },
        },
        y: {
          grid: { color: GRID },
          border: { display: false },
          ticks: {
            color: MUTED,
            font: { family: FONT_MONO, size: 11 },
            maxTicksLimit: 6,
            callback: (value) => formatRate(value),
          },
        },
      },
    },
  });

  return {
    update(history) {
      pair = { from: history.from, to: history.to };
      chart.data.labels = history.points.map((point) => dayLabel.format(new Date(point.date)));
      // Display only: the API sends exact decimal strings, and chart pixels
      // do not need more precision than a JavaScript number gives.
      chart.data.datasets[0].data = history.points.map((point) => Number(point.rate));
      chart.update();
    },
  };
}

export function formatRate(value) {
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 6 }).format(value);
}
