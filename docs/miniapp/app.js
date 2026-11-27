(function () {
  const byId = (id) => document.getElementById(id);
  const els = {
    form: byId("video-form"),
    tickers: byId("tickers"),
    selectedAssets: byId("selected-assets"),
    suggestions: byId("asset-suggestions"),
    assetSummary: byId("asset-summary"),
    assetError: byId("asset-error"),
    dateError: byId("date-error"),
    market: byId("market"),
    currency: byId("currency"),
    startDate: byId("start-date"),
    endDate: byId("end-date"),
    customDates: byId("custom-dates"),
    mode: byId("mode"),
    duration: byId("duration"),
    fps: byId("fps"),
    videoFields: byId("video-fields"),
    metric: byId("metric"),
    investment: byId("investment"),
    investmentFields: byId("investment-fields"),
    initial: byId("initial"),
    monthly: byId("monthly"),
    yearly: byId("yearly"),
    gradient: byId("gradient"),
    legend: byId("legend"),
    theme: byId("theme"),
    eventsState: byId("events-state"),
    eventsList: byId("events-list"),
    addEvent: byId("add-event-button"),
    preview: byId("request-preview"),
    manualCopy: byId("manual-copy"),
    send: byId("send-button"),
    hint: byId("action-hint"),
    status: byId("status-text"),
  };
  const catalog = (window.marketMotionCatalog || []).map(([ticker, name, engine, market, aliases = ""]) => ({
    ticker, name, engine, market, aliases: aliases.split(" "),
  }));
  const marketDefaults = {
    "": ["stock", "shares"],
    global: ["global", "stocks"],
    metals: ["global", "metals"],
    crypto: ["global", "crypto"],
    futures: ["futures", "forts"],
    selt: ["currency", "selt"],
  };
  const tickerPattern = /^[A-Z0-9^][A-Z0-9._=\/^\-]{0,20}$/i;
  const periodButtons = document.querySelectorAll("[data-period]");
  const presetButtons = document.querySelectorAll("[data-tickers]");
  const launch = new URLSearchParams(window.location.search).get("launch");
  const copyDestination = launch === "group" ? "ответом на сообщение бота" : "в чат с ботом";
  let tg = null;
  let submitting = false;
  let assets = [];
  let suggestions = [];
  let activeSuggestion = -1;
  let currencyWasSet = false;

  function canSendToTelegram() {
    return Boolean(tg && launch === "keyboard" && !tg.initData && typeof tg.sendData === "function");
  }

  function updateAction() {
    const send = canSendToTelegram();
    els.send.textContent = send ? "Создать видео" : "Скопировать запрос";
    els.hint.textContent = send
      ? "Готовое видео придёт в этот чат."
      : `Отправьте запрос ${copyDestination}. Там появится видео.`;
  }

  function initTelegram() {
    const bridge = window.Telegram && window.Telegram.WebApp;
    if (!bridge || tg || !(bridge.initData || (bridge.platform && bridge.platform !== "unknown"))) {
      return;
    }
    tg = bridge;
    updateAction();
    if (typeof tg.ready === "function") {
      tg.ready();
    }
    if (typeof tg.expand === "function") {
      tg.expand();
    }
  }

  function localDate(date) {
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${date.getFullYear()}-${month}-${day}`;
  }

  function selectPeriod(period) {
    const custom = period === "custom";
    els.customDates.hidden = !custom;
    periodButtons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.period === period));
    });
    if (!custom) {
      const end = new Date();
      const year = end.getFullYear() - Number(period);
      const month = end.getMonth();
      const lastDay = new Date(year, month + 1, 0).getDate();
      const start = new Date(year, month, Math.min(lastDay, end.getDate()));
      els.startDate.value = localDate(start);
      els.endDate.value = localDate(end);
    }
  }

  function normalizedQuery(value) {
    return value.trim().toLowerCase().replace(/ё/g, "е");
  }

  function manualAsset(value) {
    const [rawTicker, engine, market, rest] = value.split("|");
    if (!tickerPattern.test(rawTicker) || rest !== undefined ||
        (engine !== undefined && (!/^(stock|global|currency|futures)$/i.test(engine) || !/^[a-z0-9_-]+$/i.test(market || "")))) {
      return null;
    }
    const ticker = rawTicker.toUpperCase();
    return {
      ticker, name: ticker,
      engine: engine ? engine.toLowerCase() : "", market: market ? market.toLowerCase() : "",
    };
  }

  function assetSource(asset) {
    if (asset.engine) {
      return [asset.engine, asset.market];
    }
    if (els.market.value) {
      return marketDefaults[els.market.value];
    }
    if (asset.ticker.endsWith("-USD")) {
      return ["global", "crypto"];
    }
    if (asset.ticker.endsWith("=F")) {
      return ["global", "futures"];
    }
    if (asset.ticker.endsWith("=X")) {
      return ["global", "currency"];
    }
    if (asset.ticker.startsWith("^") || asset.ticker.includes(".")) {
      return ["global", "stocks"];
    }
    return marketDefaults[""];
  }

  function assetSpec(asset) {
    return [asset.ticker, ...assetSource(asset)].join("|");
  }

  function exactAsset(term) {
    const query = normalizedQuery(term);
    return catalog.find((asset) => [asset.ticker, asset.name, ...asset.aliases].some((value) => normalizedQuery(value) === query));
  }

  function closeSuggestions() {
    els.suggestions.hidden = true;
    els.tickers.setAttribute("aria-expanded", "false");
    els.tickers.removeAttribute("aria-activedescendant");
    activeSuggestion = -1;
  }

  function highlightSuggestion(index) {
    activeSuggestion = index;
    Array.from(els.suggestions.children).forEach((option, optionIndex) => {
      option.setAttribute("aria-selected", String(optionIndex === index));
    });
    const option = els.suggestions.children[index];
    els.tickers.setAttribute("aria-activedescendant", option.id);
  }

  function updateSuggestions() {
    closeSuggestions();
    els.suggestions.textContent = "";
    const query = normalizedQuery(els.tickers.value);
    if (!query) {
      return;
    }

    const matches = catalog.map((asset) => {
      const words = [asset.ticker, asset.name, ...asset.aliases].map(normalizedQuery);
      const rank = words.includes(query) ? 0 : words.some((word) => word.startsWith(query)) ? 1 : 2;
      return { asset, rank, matches: words.some((word) => word.includes(query)) };
    }).filter((entry) => entry.matches)
      .sort((left, right) => left.rank - right.rank)
      .slice(0, 5);
    suggestions = matches.map(({ asset }) => ({ assets: [asset], label: asset.name, tickers: asset.ticker }));
    const terms = els.tickers.value.trim().split(/[\s,;]+/).filter(Boolean);
    const typedAssets = terms.map((term) => {
      const mayBeTicker = terms.length === 1 || term === term.toUpperCase();
      return exactAsset(term) || (mayBeTicker ? manualAsset(term) : null);
    });
    if (typedAssets.length && typedAssets.every(Boolean) && !exactAsset(query)) {
      const tickers = typedAssets.map((asset) => asset.ticker).join(", ");
      suggestions.push({ assets: typedAssets, label: "Добавить " + tickers, tickers: "" });
    }

    suggestions.forEach(({ label, tickers }, index) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "asset-option";
      option.id = "asset-option-" + index;
      option.tabIndex = -1;
      option.dataset.suggestion = String(index);
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      const name = document.createElement("span");
      name.className = "asset-option-name";
      name.textContent = label;
      const ticker = document.createElement("span");
      ticker.className = "asset-option-ticker";
      ticker.textContent = tickers;
      option.append(name, ticker);
      els.suggestions.append(option);
    });
    if (!suggestions.length) {
      const note = document.createElement("p");
      note.className = "asset-no-results";
      note.textContent = "Ничего не нашли. Попробуйте другое название или введите тикер латиницей.";
      note.setAttribute("role", "status");
      els.suggestions.append(note);
    }
    els.suggestions.hidden = false;
    els.tickers.setAttribute("aria-expanded", String(suggestions.length > 0));
  }

  function updateSelection(preferredCurrency) {
    els.selectedAssets.textContent = "";
    assets.forEach((asset, index) => {
      const chip = document.createElement("span");
      chip.className = "asset-chip";
      const name = document.createElement("span");
      name.className = "asset-chip-label";
      name.textContent = asset.name;
      chip.append(name);
      if (asset.name !== asset.ticker) {
        const ticker = document.createElement("span");
        ticker.className = "asset-chip-ticker";
        ticker.textContent = asset.ticker;
        chip.append(ticker);
      }
      const remove = document.createElement("button");
      remove.className = "asset-remove";
      remove.type = "button";
      remove.dataset.removeAsset = String(index);
      remove.setAttribute("aria-label", "Удалить " + asset.name);
      remove.textContent = "×";
      chip.append(remove);
      els.selectedAssets.append(chip);
    });
    els.selectedAssets.hidden = assets.length === 0;
    els.assetSummary.hidden = assets.length === 0;
    const word = { one: "актив", few: "актива", many: "активов" };
    els.assetSummary.textContent = assets.length + " " + word[new Intl.PluralRules("ru").select(assets.length)];
    if (!currencyWasSet) {
      const onlyGlobal = assets.length && assets.every((asset) => assetSource(asset)[0] === "global");
      els.currency.value = preferredCurrency || (onlyGlobal ? "USD" : "RUB");
    }
    clearError(els.assetError, [els.tickers]);
    update();
  }

  function applySuggestion(index) {
    const suggestion = suggestions[index];
    for (const asset of suggestion.assets) {
      if (!assets.some((selected) => assetSpec(selected) === assetSpec(asset))) {
        assets.push(asset);
      }
    }
    els.tickers.value = "";
    closeSuggestions();
    updateSelection();
    els.tickers.focus();
  }

  function clearError(container, fields) {
    container.hidden = true;
    container.textContent = "";
    fields.forEach((field) => field.removeAttribute("aria-invalid"));
  }

  function fieldError(field, container, message) {
    container.hidden = false;
    container.textContent = message;
    field.setAttribute("aria-invalid", "true");
    field.focus();
  }

  function readPositiveInt(input, fallback) {
    const value = Number.parseInt(input.value, 10);
    return Number.isFinite(value) ? value : fallback;
  }

  function eventRows() {
    return Array.from(els.eventsList.querySelectorAll(".event-row"));
  }

  function eventRowValue(row) {
    return {
      title: row.querySelector("[data-event-title]").value.trim(),
      start: row.querySelector("[data-event-start]").value,
      end: row.querySelector("[data-event-end]").value,
      impact: row.querySelector("[data-event-impact]").value,
    };
  }

  function eventWord(count) {
    const mod10 = count % 10;
    const mod100 = count % 100;
    if (mod10 === 1 && mod100 !== 11) {
      return "событие";
    }
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
      return "события";
    }
    return "событий";
  }

  function completeEventCount() {
    return eventRows().filter((row) => {
      const event = eventRowValue(row);
      return event.title && event.start && event.end;
    }).length;
  }

  function updateEventsState() {
    const count = completeEventCount();
    els.eventsState.hidden = count === 0;
    els.eventsState.textContent = `${count} ${eventWord(count)}`;
  }

  function createEventRow() {
    const row = document.createElement("article");
    row.className = "event-row";
    row.innerHTML = `
      <div class="event-row-head">
        <strong>Событие</strong>
        <button class="remove-event-button" type="button" aria-label="Удалить событие">Удалить</button>
      </div>
      <label class="field">
        <span class="field-label">Название</span>
        <input class="text-input" data-event-title maxlength="80" placeholder="Смягчение ФРС" autocomplete="off">
      </label>
      <div class="field-grid">
        <label class="field">
          <span class="field-label">С</span>
          <input class="text-input" data-event-start type="date">
        </label>
        <label class="field">
          <span class="field-label">До</span>
          <input class="text-input" data-event-end type="date">
        </label>
        <label class="field">
          <span class="field-label">Влияние</span>
          <select class="select-input" data-event-impact>
            <option value="0">Нейтральное</option>
            <option value="1">Позитивное</option>
            <option value="-1">Негативное</option>
          </select>
        </label>
      </div>
    `;
    row.querySelector(".remove-event-button").addEventListener("click", () => {
      row.remove();
      update();
    });
    els.eventsList.appendChild(row);
    row.querySelector("[data-event-title]").focus();
    update();
  }

  function readTimelineEvents() {
    const events = [];
    for (const row of eventRows()) {
      const event = eventRowValue(row);
      const dirty = event.title || event.start || event.end;
      if (!dirty) {
        continue;
      }
      if (!event.title || !event.start || !event.end) {
        return { events: [], error: "Заполните название и обе даты события." };
      }
      if (event.start > event.end) {
        return { events: [], error: `У события «${event.title}» дата начала позже даты окончания.` };
      }
      if (event.start < els.startDate.value || event.end > els.endDate.value) {
        return { events: [], error: `Событие «${event.title}» должно находиться внутри периода графика.` };
      }
      events.push(event);
    }
    return { events, error: "" };
  }

  function buildRequest() {
    const duration = readPositiveInt(els.duration, 16);
    const fps = readPositiveInt(els.fps, 24);
    const parts = [];

    if (els.tickers.value.trim()) {
      return { field: els.tickers, error: "Выберите актив в списке или очистите поиск." };
    }
    if (!assets.length) {
      return { field: els.tickers, error: "Выберите хотя бы один актив." };
    }
    if (!els.startDate.value || !els.endDate.value) {
      return { field: els.startDate.value ? els.endDate : els.startDate, error: "Укажите обе даты периода." };
    }
    if (els.startDate.value >= els.endDate.value) {
      return { field: els.endDate, error: "Дата окончания должна быть позже даты начала." };
    }
    if (els.mode.value === "custom" && !els.duration.validity.valid) {
      return { text: "", error: "Укажите длину видео от 1 до 90 секунд." };
    }
    if (els.mode.value === "custom" && !els.fps.validity.valid) {
      return { text: "", error: "Укажите частоту от 1 до 30 кадров в секунду." };
    }
    const timelineEvents = readTimelineEvents();
    if (timelineEvents.error) {
      return { text: "", error: timelineEvents.error };
    }

    parts.push(...assets.map(assetSpec));
    parts.push(`from=${els.startDate.value}`);
    parts.push(`to=${els.endDate.value}`);
    parts.push(els.currency.value);
    parts.push(els.metric.value);

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
    timelineEvents.events.forEach((event) => {
      parts.push(`event=${event.start}~${event.end}~${encodeURIComponent(event.title).replace(/~/g, "%7E")}~${event.impact}`);
    });

    return { text: parts.join(" "), error: "" };
  }

  function updateStatus(message, ok) {
    els.status.textContent = message;
    els.status.classList.toggle("is-ok", Boolean(ok));
  }

  function update() {
    presetButtons.forEach((button) => {
      const tickers = button.dataset.tickers.split(/\s+/).map((ticker) => (exactAsset(ticker) || manualAsset(ticker)).ticker);
      const selected = tickers.length === assets.length && tickers.every((ticker, index) => assets[index].ticker === ticker);
      button.setAttribute("aria-pressed", String(selected));
    });
    els.investmentFields.hidden = !els.investment.checked;
    els.videoFields.hidden = els.mode.value !== "custom";
    els.addEvent.disabled = eventRows().length >= 12;
    els.manualCopy.hidden = true;
    updateEventsState();
    updateStatus("");
  }

  async function copyRequest(text, message) {
    els.preview.value = text;
    try {
      await navigator.clipboard.writeText(text);
      updateStatus(message || `Запрос скопирован. Отправьте его ${copyDestination}.`, true);
    } catch {
      els.manualCopy.hidden = false;
      els.preview.focus();
      els.preview.select();
      updateStatus(`Скопируйте выделенный запрос и отправьте его ${copyDestination}.`);
    }
  }

  async function submitRequest(event) {
    event.preventDefault();
    if (submitting) {
      return;
    }
    const result = buildRequest();
    if (result.error) {
      if (result.field === els.tickers) {
        fieldError(els.tickers, els.assetError, result.error);
        updateSuggestions();
      } else if (result.field) {
        fieldError(result.field, els.dateError, result.error);
      } else {
        updateStatus(result.error);
      }
      return;
    }

    const text = result.text;
    if (text.length > 4096) {
      updateStatus("Запрос не помещается в сообщение Telegram. Сократите названия событий или уберите часть событий.");
      return;
    }

    submitting = true;
    els.send.disabled = true;
    const payload = JSON.stringify({
      type: "stock_prices.video_request.v1",
      text: result.text,
      source: "telegram-mini-app",
    });
    try {
      if (canSendToTelegram() && new Blob([payload]).size <= 4096) {
        tg.sendData(payload);
        updateStatus("Запрос передан в Telegram. Статус появится в чате с ботом.", true);
      } else {
        await copyRequest(text);
      }
    } catch {
      await copyRequest(text, "Прямая отправка недоступна. Запрос скопирован для отправки в чат с ботом.");
    } finally {
      submitting = false;
      els.send.disabled = false;
    }
  }

  periodButtons.forEach((button) => {
    button.addEventListener("click", () => {
      selectPeriod(button.dataset.period);
      clearError(els.dateError, [els.startDate, els.endDate]);
      update();
    });
  });
  presetButtons.forEach((button) => {
    button.addEventListener("click", () => {
      assets = button.dataset.tickers.split(/\s+/).map((ticker) => exactAsset(ticker) || manualAsset(ticker));
      currencyWasSet = false;
      els.tickers.value = "";
      closeSuggestions();
      updateSelection(button.dataset.currency);
    });
  });
  els.tickers.setAttribute("role", "combobox");
  els.tickers.setAttribute("aria-autocomplete", "list");
  els.tickers.setAttribute("aria-controls", els.suggestions.id);
  els.suggestions.setAttribute("role", "listbox");
  els.suggestions.setAttribute("aria-label", "Результаты поиска");
  [els.tickers, els.startDate, els.endDate].forEach((field) => {
    const error = field === els.tickers ? els.assetError : els.dateError;
    const describedBy = new Set((field.getAttribute("aria-describedby") || "").split(" ").filter(Boolean));
    describedBy.add(error.id);
    field.setAttribute("aria-describedby", Array.from(describedBy).join(" "));
  });
  els.tickers.addEventListener("focus", () => {
    if (els.tickers.value.trim()) {
      updateSuggestions();
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (event.target !== els.tickers && !els.suggestions.contains(event.target)) {
      closeSuggestions();
    }
  });
  els.tickers.addEventListener("input", () => {
    clearError(els.assetError, [els.tickers]);
    updateSuggestions();
  });
  els.tickers.addEventListener("keydown", (event) => {
    if (event.isComposing) {
      return;
    }
    if (event.key === "Escape") {
      closeSuggestions();
    } else if (event.key === "Enter" && els.tickers.value.trim()) {
      event.preventDefault();
      if (!els.suggestions.hidden && suggestions.length) {
        applySuggestion(Math.max(activeSuggestion, 0));
      }
    } else if (["ArrowDown", "ArrowUp"].includes(event.key) && !els.suggestions.hidden && suggestions.length) {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      const index = activeSuggestion === -1 && step === -1 ? suggestions.length - 1 : activeSuggestion + step;
      highlightSuggestion((index + suggestions.length) % suggestions.length);
    }
  });
  els.suggestions.addEventListener("click", (event) => {
    const option = event.target.closest("[data-suggestion]");
    if (option) {
      applySuggestion(Number(option.dataset.suggestion));
    }
  });
  els.selectedAssets.addEventListener("click", (event) => {
    const remove = event.target.closest("[data-remove-asset]");
    if (remove) {
      const index = Number(remove.dataset.removeAsset);
      assets.splice(index, 1);
      updateSelection();
      const next = els.selectedAssets.querySelector(`[data-remove-asset="${Math.min(index, assets.length - 1)}"]`);
      (next || els.tickers).focus();
    }
  });
  els.currency.addEventListener("change", () => {
    currencyWasSet = true;
  });
  els.market.addEventListener("change", () => updateSelection());
  [els.startDate, els.endDate].forEach((field) => field.addEventListener("input", () => {
    clearError(els.dateError, [els.startDate, els.endDate]);
  }));
  els.mode.addEventListener("change", () => {
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
  });
  els.addEvent.addEventListener("click", createEventRow);
  els.form.addEventListener("input", (event) => {
    if (event.target !== els.preview) {
      update();
    }
  });
  els.form.addEventListener("change", (event) => {
    if (event.target !== els.preview) {
      update();
    }
  });
  els.form.addEventListener("submit", submitRequest);
  const example = document.querySelector(".example");
  const videoTemplate = example.querySelector("template");
  example.querySelector("summary").addEventListener("click", (event) => {
    if (example.open) {
      return;
    }
    event.preventDefault();
    example.open = true;
    if (!example.querySelector("video")) {
      example.appendChild(videoTemplate.content.cloneNode(true));
    }
    example.querySelector("video").play().catch(() => {});
  });
  example.addEventListener("toggle", () => {
    const video = example.querySelector("video");
    if (!example.open && video) {
      video.pause();
    }
  });

  selectPeriod("1");
  closeSuggestions();
  updateSelection();
  updateAction();
  byId("telegram-sdk").addEventListener("load", initTelegram);
  initTelegram();
})();
