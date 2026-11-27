(function () {
  const byId = (id) => document.getElementById(id);
  const els = {
    form: byId("video-form"),
    tickers: byId("tickers"),
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
  const periodButtons = document.querySelectorAll("[data-period]");
  const presetButtons = document.querySelectorAll("[data-tickers]");
  const launch = new URLSearchParams(window.location.search).get("launch");
  const copyDestination = launch === "group" ? "ответом на сообщение бота" : "в чат с ботом";
  let tg = null;
  let submitting = false;

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

  function normalizedTickers() {
    return els.tickers.value.split(/[\s,;]+/).filter(Boolean).join(" ");
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
    const tickers = normalizedTickers();
    const duration = readPositiveInt(els.duration, 16);
    const fps = readPositiveInt(els.fps, 24);
    const parts = [];

    if (!tickers) {
      return { text: "", error: "Укажите хотя бы один тикер." };
    }
    if (!els.startDate.value || !els.endDate.value) {
      return { text: "", error: "Укажите обе даты периода." };
    }
    if (els.startDate.value >= els.endDate.value) {
      return { text: "", error: "Дата начала должна быть раньше даты окончания." };
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

    parts.push(tickers);
    parts.push(`from=${els.startDate.value}`);
    parts.push(`to=${els.endDate.value}`);
    if (els.market.value) {
      parts.push(els.market.value);
    }
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
    const tickers = normalizedTickers().toUpperCase();
    presetButtons.forEach((button) => {
      const selected = button.dataset.tickers.toUpperCase() === tickers &&
        button.dataset.market === els.market.value && button.dataset.currency === els.currency.value;
      button.setAttribute("aria-pressed", String(selected));
    });
    els.investmentFields.hidden = !els.investment.checked;
    els.videoFields.hidden = els.mode.value !== "custom";
    els.addEvent.disabled = eventRows().length >= 12;
    els.manualCopy.hidden = true;
    els.tickers.removeAttribute("aria-invalid");
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
      if (!normalizedTickers()) {
        els.tickers.setAttribute("aria-invalid", "true");
        els.tickers.focus();
      }
      updateStatus(result.error);
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
      update();
    });
  });
  presetButtons.forEach((button) => {
    button.addEventListener("click", () => {
      els.tickers.value = button.dataset.tickers;
      els.market.value = button.dataset.market;
      els.currency.value = button.dataset.currency;
      update();
    });
  });
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
  example.addEventListener("toggle", () => {
    const video = example.querySelector("video");
    if (example.open && !video) {
      example.appendChild(videoTemplate.content.cloneNode(true));
    } else if (!example.open && video) {
      video.pause();
    }
  });

  selectPeriod("1");
  update();
  updateAction();
  byId("telegram-sdk").addEventListener("load", initTelegram);
  initTelegram();
})();
