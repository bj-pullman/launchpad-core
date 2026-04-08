document.addEventListener("DOMContentLoaded", function () {
  initStaffStatusOverview();
});

function initStaffStatusOverview() {
  const data = window.staffStatusOverviewData;
  if (!data) return;

  buildLocationDistributionChart(data);
  buildTopLocationsChart(data);
  buildTrendChart(data);
}

function buildLocationDistributionChart(data) {
  const canvas = document.getElementById("staff-status-location-distribution-chart");
  const empty = document.getElementById("staff-status-location-distribution-empty");
  if (!canvas) return;

  const rows = Array.isArray(data.location_distribution) ? data.location_distribution : [];
  if (!rows.length) {
    canvas.style.display = "none";
    if (empty) empty.hidden = false;
    return;
  }

  new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: rows.map((item) => item.label),
      datasets: [
        {
          data: rows.map((item) => item.count),
          borderWidth: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "bottom"
        }
      }
    }
  });
}

function buildTopLocationsChart(data) {
  const canvas = document.getElementById("staff-status-top-locations-chart");
  const empty = document.getElementById("staff-status-top-locations-empty");
  if (!canvas) return;

  const rows = Array.isArray(data.top_locations) ? data.top_locations : [];
  if (!rows.length) {
    canvas.style.display = "none";
    if (empty) empty.hidden = false;
    return;
  }

  new Chart(canvas, {
    type: "bar",
    data: {
      labels: rows.map((item) => item.label),
      datasets: [
        {
          label: "Updates",
          data: rows.map((item) => item.count),
          borderWidth: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      scales: {
        x: {
          beginAtZero: true,
          ticks: {
            precision: 0
          }
        }
      },
      plugins: {
        legend: {
          display: false
        }
      }
    }
  });
}

function buildTrendChart(data) {
  const canvas = document.getElementById("staff-status-trend-chart");
  const empty = document.getElementById("staff-status-trend-empty");
  if (!canvas) return;

  const rows = Array.isArray(data.trend_points) ? data.trend_points : [];
  if (!rows.length) {
    canvas.style.display = "none";
    if (empty) empty.hidden = false;
    return;
  }

  new Chart(canvas, {
    type: "line",
    data: {
      labels: rows.map((item) => item.bucket),
      datasets: [
        {
          label: "Location Updates",
          data: rows.map((item) => item.count),
          tension: 0.25,
          fill: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            precision: 0
          }
        }
      }
    }
  });
}