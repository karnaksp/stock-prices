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
    previewRange: document.getElementById("preview-range"),
    previewFormat: document.getElementById("preview-format"),
    previewCurrency: document.getElementById("preview-currency"),
    send: document.getElementById("send-button"),
    copy: document.getElementById("copy-button"),
    error: document.getElementById("error-text"),
    telegramStatus: document.getElementById("telegram-status"),
    modeStatus: document.getElementById("mode-status"),
    storyTitle: document.getElementById("story-title"),
    tickerSummary: document.getElementById("ticker-summary"),
    assetsSummary: document.getElementById("assets-summary"),
    historySummary: document.getElementById("history-summary"),
    calcSummary: document.getElementById("calc-summary"),
    formatSummary: document.getElementById("format-summary"),
    dockTitle: document.getElementById("dock-title"),
  };

  const modeLabels = {
    shorts: "Shorts",
    draft: "Draft",
    custom: "Custom",
  };

  const marketLabels = {
    "": "Auto / MOEX",
    global: "Global",
    metals: "Metals",
    futures: "Futures",
    crypto: "Crypto",
    selt: "Currency",
  };

  function isTelegramLaunch() {
    return Boolean(tg && (tg.initData || (tg.platform && tg.platform !== "unknown")));
  }

  function canSendToTelegram() {
    return Boolean(tg && typeof tg.sendData === "function" && isTelegramLaunch());
  }

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

  function tickerList() {
    return els.tickers.value
      .split(/[\s,;]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function normalizedTickers() {
    return tickerList().join(" ");
  }

  function readPositiveInt(input, fallback) {
    const value = Number.parseInt(input.value, 10);
    return Number.isFinite(value) ? value : fallback;
  }

  function clampNumberInput(input, min, max) {
    const value = readPositiveInt(input, min);
    input.value = String(Math.min(max, Math.max(min, value)));
  }

  function yearWord(years) {
    const mod10 = years % 10;
    const mod100 = years % 100;
    if (mod10 === 1 && mod100 !== 11) {
      return "год";
    }
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
      return "года";
    }
    return "лет";
  }

  function formatPeriodLabel() {
    if (!els.startDate.value || !els.endDate.value) {
      return "Период";
    }
    const start = new Date(`${els.startDate.value}T00:00:00`);
    const end = new Date(`${els.endDate.value}T00:00:00`);
    const years = Math.max(0, (end - start) / (365.25 * 24 * 60 * 60 * 1000));
    if (years >= 1) {
      const roundedYears = Math.round(years);
      if (Math.abs(years - roundedYears) < 0.05) {
        return `${roundedYears} ${yearWord(roundedYears)}`;
      }
      return `${years.toFixed(years >= 10 ? 0 : 1)} лет`;
    }
    return `${Math.max(1, Math.round(years * 12))} мес`;
  }

  function formatMoney(value, currency) {
    return new Intl.NumberFormat("ru-RU", {
      maximumFractionDigits: 0,
      style: "currency",
      currency,
    }).format(value);
  }

  function formatTickersForTitle() {
    const tickers = tickerList();
    if (!tickers.length) {
      return "тикеров";
    }
    return tickers.slice(0, 4).join(" / ");
  }

  function setActiveButtons(selector, activeValue, dataKey) {
    document.querySelectorAll(selector).forEach((button) => {
      button.classList.toggle("active", button.dataset[dataKey] === activeValue);
    });
  }

  function syncVisualControls() {
    setActiveButtons("[data-mode]", els.mode.value, "mode");
    setActiveButtons("[data-metric]", els.metricCapital.checked ? "capital" : "close", "metric");
    document.querySelectorAll("[data-tickers]").forEach((button) => {
      button.classList.toggle("active", button.dataset.tickers === normalizedTickers());
    });
  }

  function renderTickerSummary() {
    const tickers = tickerList();
    els.tickerSummary.replaceChildren();
    if (!tickers.length) {
      const empty = document.createElement("span");
      empty.textContent = "Введите тикер";
      els.tickerSummary.appendChild(empty);
      return;
    }
    tickers.slice(0, 5).forEach((ticker) => {
      const chip = document.createElement("span");
      chip.textContent = ticker;
      els.tickerSummary.appendChild(chip);
    });
    if (tickers.length > 5) {
      const more = document.createElement("span");
      more.textContent = `+${tickers.length - 5}`;
      els.tickerSummary.appendChild(more);
    }
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
    if (!isTelegramLaunch() || !tg.MainButton) {
      return;
    }
    tg.MainButton.setText("Отправить в бот");
    if (error || !text) {
      tg.MainButton.disable();
      tg.MainButton.hide();
    } else {
      tg.MainButton.enable();
      tg.MainButton.show();
    }
  }

  function updateStatus(message, ok) {
    els.error.textContent = message;
    els.error.classList.toggle("is-ok", Boolean(ok));
  }

  function updatePreviewMeta() {
    const duration = readPositiveInt(els.duration, 16);
    const fps = readPositiveInt(els.fps, 24);
    const period = formatPeriodLabel();
    const tickersTitle = formatTickersForTitle();
    const market = marketLabels[els.market.value] || els.market.value || "Auto / MOEX";
    const metric = els.metricCapital.checked ? "Капитал" : "Цена";
    const monthly = Math.max(0, readPositiveInt(els.monthly, 0));
    const investmentText = els.investment.checked
      ? `Инвестиции · ${formatMoney(monthly, els.currency.value)} / мес`
      : metric;

    els.previewRange.textContent = period;
    els.previewFormat.textContent = `${duration}s / ${fps}fps`;
    els.previewCurrency.textContent = els.currency.value;
    els.modeStatus.textContent = modeLabels[els.mode.value] || "Custom";
    els.assetsSummary.textContent = `${market} · ${els.currency.value}`;
    els.historySummary.textContent = period;
    els.calcSummary.textContent = investmentText;
    els.formatSummary.textContent = `${duration}s · ${fps}fps`;
    els.storyTitle.textContent = els.investment.checked
      ? `Что было бы с ${formatMoney(monthly, els.currency.value)} каждый месяц?`
      : `Видео из ${tickersTitle}`;
    els.dockTitle.textContent = `Видео из ${tickersTitle}`;
  }

  function update() {
    clampNumberInput(els.duration, 1, 90);
    clampNumberInput(els.fps, 1, 30);
    els.investmentFields.hidden = !els.investment.checked;
    syncVisualControls();
    renderTickerSummary();
    updatePreviewMeta();
    const result = buildRequest();
    els.preview.textContent = result.text || "SBER LKOH from=2020-01-01 to=2024-12-31 RUB capital shorts";
    updateStatus(result.error, false);
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
    if (canSendToTelegram()) {
      tg.sendData(payload);
      updateStatus("Запрос отправлен. Если чат не обновился, открой Mini App через /app.", true);
      return;
    }
    copyText(result.text)
      .then(() => {
        updateStatus("Запрос скопирован. Чтобы отправить напрямую, открой Mini App из чата через /app.", true);
      })
      .catch(() => {
        updateStatus("Не удалось отправить напрямую. Открой Mini App из чата через /app.", false);
      });
  }

  function initTelegram() {
    if (!isTelegramLaunch()) {
      els.telegramStatus.textContent = "Browser";
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

  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      els.mode.value = button.dataset.mode || "shorts";
      applyModeDefaults();
    });
  });

  document.querySelectorAll("[data-metric]").forEach((button) => {
    button.addEventListener("click", () => {
      els.metricCapital.checked = button.dataset.metric === "capital";
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

  els.send.addEventListener("click", submitRequest);
  els.copy.addEventListener("click", () => {
    const result = update();
    if (!result.error) {
      copyText(result.text).then(() => {
        updateStatus("Запрос скопирован.", true);
      }).catch(() => {
        updateStatus("Не удалось скопировать запрос.", false);
      });
    }
  });

  els.endDate.value = todayIso();
  setPeriod(10);
  initTelegram();
  update();
})();
