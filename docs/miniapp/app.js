(function () {
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

  const els = {
    tickers: document.getElementById("tickers"),
    market: document.getElementById("market"),
    currency: document.getElementById("currency"),
    startDate: document.getElementById("start-date"),
    endDate: document.getElementById("end-date"),
    mode: document.getElementById("mode"),
    duration: document.getElementById("duration"),
    fps: document.getElementById("fps"),
    metricCapital: document.getElementById("metric-capital"),
    investment: document.getElementById("investment"),
    investmentFields: document.getElementById("investment-fields"),
    initial: document.getElementById("initial"),
    monthly: document.getElementById("monthly"),
    yearly: document.getElementById("yearly"),
    gradient: document.getElementById("gradient"),
    legend: document.getElementById("legend"),
    theme: document.getElementById("theme"),
    preview: document.getElementById("request-preview"),
    send: document.getElementById("send-button"),
    copy: document.getElementById("copy-button"),
    error: document.getElementById("error-text"),
    telegramStatus: document.getElementById("telegram-status"),
  };

  function todayIso() {
    return new Date().toISOString().slice(0, 10);
  }

  function addYears(date, years) {
    const next = new Date(date);
    next.setFullYear(next.getFullYear() + years);
    return next;
  }

  function setPeriod(years) {
    const end = new Date();
    const start = addYears(end, -years);
    els.startDate.value = start.toISOString().slice(0, 10);
    els.endDate.value = end.toISOString().slice(0, 10);
  }

  function normalizedTickers() {
    return els.tickers.value
      .split(/[\s,;]+/)
      .map((item) => item.trim())
      .filter(Boolean)
      .join(" ");
  }

  function readPositiveInt(input, fallback) {
    const value = Number.parseInt(input.value, 10);
    return Number.isFinite(value) ? value : fallback;
  }

  function clampNumberInput(input, min, max) {
    const value = readPositiveInt(input, min);
    input.value = String(Math.min(max, Math.max(min, value)));
  }

  function buildRequest() {
    const tickers = normalizedTickers();
    const duration = readPositiveInt(els.duration, 16);
    const fps = readPositiveInt(els.fps, 24);
    const parts = [];

    if (!tickers) {
      return { text: "", error: "Укажи хотя бы один тикер." };
    }
    if (!els.startDate.value || !els.endDate.value) {
      return { text: "", error: "Укажи период." };
    }
    if (els.startDate.value > els.endDate.value) {
      return { text: "", error: "Дата начала должна быть раньше даты конца." };
    }
    if (duration < 1 || duration > 90) {
      return { text: "", error: "Длина видео: 1-90 секунд." };
    }
    if (fps < 1 || fps > 30) {
      return { text: "", error: "FPS: 1-30." };
    }

    parts.push(tickers);
    parts.push(`from=${els.startDate.value}`);
    parts.push(`to=${els.endDate.value}`);
    if (els.market.value) {
      parts.push(els.market.value);
    }
    parts.push(els.currency.value);
    parts.push(els.metricCapital.checked ? "capital" : "close");

    if (els.investment.checked) {
      parts.push("invest");
      parts.push(`initial=${Math.max(0, readPositiveInt(els.initial, 0))}`);
      parts.push(`monthly=${Math.max(0, readPositiveInt(els.monthly, 0))}`);
      const yearly = Math.max(0, readPositiveInt(els.yearly, 0));
      if (yearly > 0) {
        parts.push(`yearly=${yearly}`);
      }
    }

    if (els.mode.value === "shorts") {
      parts.push("shorts");
    } else if (els.mode.value === "draft") {
      parts.push("draft");
    } else {
      parts.push(`duration=${duration}`);
      parts.push(`fps=${fps}`);
    }

    parts.push(els.gradient.checked ? "gradient" : "nogradient");
    if (!els.legend.checked) {
      parts.push("nolegend");
    }
    parts.push(`theme=${els.theme.value}`);

    return { text: parts.join(" "), error: "" };
  }

  function applyModeDefaults() {
    if (els.mode.value === "shorts") {
      els.duration.value = "16";
      els.fps.value = "24";
      els.gradient.checked = true;
    } else if (els.mode.value === "draft") {
      els.duration.value = "4";
      els.fps.value = "8";
      els.gradient.checked = false;
    }
    update();
  }

  function updateTelegramButton(text, error) {
    if (!tg || !tg.MainButton) {
      return;
    }
    tg.MainButton.setText("Отправить в бота");
    if (error || !text) {
      tg.MainButton.disable();
      tg.MainButton.hide();
    } else {
      tg.MainButton.enable();
      tg.MainButton.show();
    }
  }

  function update() {
    clampNumberInput(els.duration, 1, 90);
    clampNumberInput(els.fps, 1, 30);
    els.investmentFields.hidden = !els.investment.checked;
    const result = buildRequest();
    els.preview.textContent = result.text || "SBER LKOH from=2020-01-01 to=2024-12-31 RUB capital shorts";
    els.error.textContent = result.error;
    els.send.disabled = Boolean(result.error);
    updateTelegramButton(result.text, result.error);
    return result;
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }

  function submitRequest() {
    const result = update();
    if (result.error) {
      return;
    }
    const payload = JSON.stringify({
      type: "stock_prices.video_request.v1",
      text: result.text,
      source: "telegram-mini-app",
    });
    if (tg && typeof tg.sendData === "function") {
      tg.sendData(payload);
      tg.close();
      return;
    }
    copyText(result.text)
      .then(() => {
        els.error.textContent = "Запрос скопирован.";
      })
      .catch(() => {
        els.error.textContent = "Не удалось скопировать запрос.";
      });
  }

  function initTelegram() {
    if (!tg) {
      els.telegramStatus.textContent = "Browser";
      els.send.textContent = "Copy request";
      return;
    }
    tg.ready();
    tg.expand();
    els.telegramStatus.textContent = "Telegram";
    if (tg.MainButton) {
      tg.MainButton.onClick(submitRequest);
    }
  }

  document.querySelectorAll("[data-period]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-period]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      const period = button.dataset.period;
      if (period === "1y") {
        setPeriod(1);
      } else if (period === "3y") {
        setPeriod(3);
      } else if (period === "10y") {
        setPeriod(10);
      }
      update();
    });
  });

  document.querySelectorAll("[data-tickers]").forEach((button) => {
    button.addEventListener("click", () => {
      els.tickers.value = button.dataset.tickers || "";
      if (button.dataset.market !== undefined) {
        els.market.value = button.dataset.market;
      }
      if (button.dataset.currency !== undefined) {
        els.currency.value = button.dataset.currency;
      }
      update();
    });
  });

  [
    els.tickers,
    els.market,
    els.currency,
    els.startDate,
    els.endDate,
    els.duration,
    els.fps,
    els.metricCapital,
    els.investment,
    els.initial,
    els.monthly,
    els.yearly,
    els.gradient,
    els.legend,
    els.theme,
  ].forEach((element) => {
    element.addEventListener("input", update);
    element.addEventListener("change", update);
  });

  els.mode.addEventListener("change", applyModeDefaults);
  els.send.addEventListener("click", submitRequest);
  els.copy.addEventListener("click", () => {
    const result = update();
    if (!result.error) {
      copyText(result.text);
    }
  });

  els.endDate.value = todayIso();
  setPeriod(10);
  initTelegram();
  update();
})();
