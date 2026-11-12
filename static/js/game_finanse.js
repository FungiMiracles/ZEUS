"use strict";

(() => {
    const root = document.querySelector("[data-finance-root]");
    if (!root) return;

    const config = JSON.parse(
        root.querySelector("[data-finance-config]").textContent
    );

    const form = root.querySelector("[data-finance-form]");
    const errorBox = root.querySelector("[data-finance-error]");
    const previewStatus = root.querySelector("[data-finance-preview-status]");
    const submitButton = root.querySelector("[data-finance-submit]");
    const repeatButton = root.querySelector("[data-finance-repeat]");

    let displayedState = config.state;
    let busy = false;
    let previewValid = Boolean(displayedState);
    let previewVersion = 0;
    let previewController = null;
    let debounceTimer = null;

    function showError(message) {
        errorBox.textContent = message || "";
        errorBox.hidden = !message;
    }

    function decimalParts(value) {
    const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value ?? ""));
    if (!match) return null;

    const fraction = match[3] || "";
    return {
        value: BigInt((match[1] || "") + match[2] + fraction),
        scale: 10n ** BigInt(fraction.length)
    };
}

function divideCeil(numerator, denominator) {
    const quotient = numerator / denominator;
    return numerator > 0n && numerator % denominator !== 0n
        ? quotient + 1n
        : quotient;
}

function formatRatio(numerator, denominator, digits = 2) {
    const precision = 10n ** BigInt(digits);
    const rounded = divideCeil(numerator * precision, denominator);
    const negative = rounded < 0n;
    const absolute = negative ? -rounded : rounded;

    const whole = String(absolute / precision)
        .replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0");

    const fraction = digits
        ? String(absolute % precision)
            .padStart(digits, "0")
            .replace(/0+$/, "")
        : "";

    return (negative ? "-" : "") + whole +
        (fraction ? "," + fraction : "");
}

    function decimalText(value) {
        const parts = decimalParts(value);
        return parts ? formatRatio(parts.value, parts.scale) : "—";
    }

    function moneyText(value) { return window.GameMoney.format(value); }

    // Udział faktycznie przydzielonej kwoty w całym budżecie.
    // Zaokrąglenie procentu do jednego miejsca.
    function allocationPercentage(amount, total) {
        const a = decimalParts(amount);
        const t = decimalParts(total);

        if (!a || !t || t.value <= 0n || a.value < 0n) return "0,0";

        const numerator = a.value * t.scale * 1000n;
        const denominator = a.scale * t.value;
        const tenths = (numerator + denominator / 2n) / denominator;

        return `${tenths / 10n},${tenths % 10n}`;
    }

    const budgetColors = [
        "#2563eb", "#ea580c", "#16a34a", "#9333ea",
        "#0891b2", "#dc2626", "#ca8a04", "#4f46e5",
        "#0d9488", "#db2777", "#65a30d", "#7c3aed",
        "#0284c7", "#c2410c", "#475569", "#be185d",
        "#78716c"
    ];

    function renderBudgetBar(container, state) {
        container.replaceChildren();

        const bar = document.createElement("div");
        bar.className = "finance-budget-bar";
        bar.setAttribute("role", "group");
        bar.setAttribute("aria-label", "Podział dostępnych środków");

        const legend = document.createElement("div");
        legend.className = "finance-budget-legend";

        const total = decimalParts(state.budget_total);
        let visibleSegments = 0;

        config.categories.forEach((category, index) => {
            const amount = state.allocations?.[category.code] ?? "0";
            const parts = decimalParts(amount);
            if (!parts || parts.value <= 0n) return;

            const color = budgetColors[index % budgetColors.length];
            const percentage = allocationPercentage(amount, state.budget_total);
            const description =
                `${category.name}: ${moneyText(amount, true)} · ${percentage}%`;

            const segment = document.createElement("div");
            segment.className = "finance-budget-segment";
            segment.style.backgroundColor = color;

            // Waga służy wyłącznie geometrii paska.
            // Kwoty i procenty w tooltipie liczymy dokładnie przez BigInt.
            const weight = total && total.value > 0n
                ? Number(parts.value * total.scale) /
                    Number(parts.scale * total.value)
                : 0;

            segment.style.flexGrow = String(weight);
            segment.tabIndex = 0;
            segment.setAttribute("aria-label", description);

            const tooltip = document.createElement("span");
            tooltip.className = "finance-budget-tooltip";
            tooltip.textContent = description;
            segment.append(tooltip);
            bar.append(segment);

            const item = document.createElement("span");
            item.className = "finance-budget-legend-item";

            const dot = document.createElement("span");
            dot.className = "finance-budget-dot";
            dot.style.backgroundColor = color;

            item.append(dot, document.createTextNode(description));
            legend.append(item);
            visibleSegments += 1;
        });

        if (!visibleSegments) {
            const empty = document.createElement("p");
            empty.textContent = "Brak środków do podziału.";
            container.append(empty);
            return;
        }

        container.append(bar, legend);
    }

    function benefitCents(value) {
        const match=/^(\d+)(?:\.(\d{1,2}))?$/.exec(String(value));
        if(!match) throw Error('Nieprawidłowa kwota świadczenia.');
        return BigInt(match[1])*100n+BigInt((match[2] || '').padEnd(2,'0'));
    }
    function benefitAmount(value) {
        const match=/^(\d+)(?:[.,](\d{1,11}))?$/.exec(String(value));
        if(!match) throw Error('Podaj nieujemną kwotę świadczenia w MLD.');
        const cents=BigInt(match[1])*100000000000n+BigInt((match[2] || '').padEnd(11,'0'));
        return `${cents/100n}.${String(cents%100n).padStart(2,'0')}`;
    }
    function benefitBillions(value) {
        const cents=benefitCents(value);
        return `${cents/100000000000n}.${String(cents%100000000000n).padStart(11,'0')}`;
    }
    function renderState(state) {
        const benefits=state.benefits;
        const info=form.querySelector('[data-benefits-expectations]');
        if(info) info.textContent=benefits?.expected ? `Oczekiwania na półrocze: dzieci ${moneyText(benefits.expected.children)}, emerytury ${moneyText(benefits.expected.seniors)}, razem ${window.GameMoney.formatCents(benefitCents(benefits.expected.children)+benefitCents(benefits.expected.seniors))}. Przeniesione środki: ${moneyText(benefits.carry_in || '0')}.` : 'Brak struktury wieku ludności — oczekiwania świadczeń są niedostępne.';
        if(benefits?.paid) form.querySelectorAll('[data-benefit]').forEach(input=>{input.value=benefitBillions(benefits.paid[input.dataset.benefit]);});

        root.querySelectorAll("[data-value]").forEach(element => {
            const value = state[element.dataset.value];

            element.textContent = element.hasAttribute("data-money")
                ? moneyText(value)
                : decimalText(value);
        });

        root.querySelectorAll("[data-allocation]").forEach(element => {
            element.textContent = moneyText(
                state.allocations?.[element.dataset.allocation]
            );
        });

        root.querySelectorAll("[data-balance]").forEach(element => {
            element.textContent=moneyText(state.balances?.[element.dataset.sector]?.[element.dataset.balance]);
        });
        root.querySelectorAll("[data-finance-budget-chart]").forEach(container => {
            renderBudgetBar(container, state);
        });
    }

    function percentagePoints(input) {
        if (
            !input.validity.valid ||
            !/^\d+(?:\.\d{1,2})?$/.test(input.value)
        ) {
            throw new Error(
                "Udziały muszą być liczbami od 0 do 100, " +
                "z maksymalnie dwoma miejscami po przecinku."
            );
        }

        const [whole, fraction = ""] = input.value.split(".");
        const result =
            Number(whole) * 100 +
            Number(fraction.padEnd(2, "0"));

        if (result < 0 || result > 10000) {
            throw new Error("Udział musi wynosić od 0 do 100%.");
        }

        return result;
    }

    function percentageText(points) {
        return (
            Math.floor(points / 100) +
            "." +
            String(points % 100).padStart(2, "0")
        );
    }

    function readPlan() {
        if (!form) throw new Error("Formularz jest niedostępny.");

        const shares = {};
        let allocated = 0;

        form.querySelectorAll(".finance-share").forEach(input => {
            const code = input.dataset.category;
            if (code === "reserve") return;

            const points = percentagePoints(input);
            allocated += points;
            shares[code] = percentageText(points);
        });

        if (allocated > 10000) {
            throw new Error("Suma udziałów przekracza 100%.");
        }

        const reserveInput = form.querySelector(
            '[data-category="reserve"]'
        );

        reserveInput.value = percentageText(10000 - allocated);

        // Serwer sam dodaje niewykorzystany udział do rezerwy.
        shares.reserve = "0.00";

        const pit = form.elements.namedItem("pit_rate");


        return {
            pit_rate: percentageText(percentagePoints(pit)),

            shares,
            benefits: Object.fromEntries(Array.from(form.querySelectorAll("[data-benefit]")).map(input => [input.dataset.benefit,benefitAmount(input.value)]))
        };
    }

    function signature() {
        if (!form) return "";

        return JSON.stringify(
            Array.from(
                form.querySelectorAll(
                    ".finance-rate, .finance-share:not([readonly]), [data-benefit]:not([readonly])"
                ),
                input => [
                    input.name || input.dataset.category || input.dataset.benefit,
                    input.value
                ]
            )
        );
    }

    const originalSignature = signature();

    function updateButtons() {
        if (submitButton) {
            submitButton.disabled = busy || !previewValid;
        }

        if (repeatButton) {
            repeatButton.disabled = busy;
        }
    }

    function setBusy(value) {
        busy = value;

        if (form) {
            form.querySelectorAll("input").forEach(input => {
                input.disabled = value;
            });
        }

        updateButtons();
    }

    async function requestJson(url, data, signal) {
        const response = await fetch(url, {
            method: data === undefined ? "GET" : "POST",
            credentials: "same-origin",
            cache: "no-store",
            headers: data === undefined ? {} : {
                "Content-Type": "application/json",
                "X-CSRF-Token": config.csrf
            },
            body: data === undefined ? undefined : JSON.stringify(data),
            signal
        });

        const result = await response.json().catch(() => null);

        if (!response.ok || !result?.ok) {
            const error = new Error(
                result?.error ||
                "Nie udało się wykonać operacji. Odśwież stronę."
            );
            error.status = response.status;
            throw error;
        }

        return result;
    }

    function cancelPreview() {
        clearTimeout(debounceTimer);
        previewVersion += 1;
        previewController?.abort();
        previewController = null;
    }

    async function refreshPreview() {
        cancelPreview();

        const version = previewVersion;
        const controller = new AbortController();
        previewController = controller;

        previewValid = false;
        updateButtons();

        try {
            const plan = readPlan();

            if (previewStatus) {
                previewStatus.textContent = "Przeliczanie podglądu…";
            }

            const result = await requestJson(
                config.previewUrl,
                plan,
                controller.signal
            );

            if (version !== previewVersion) return;

            if (result.state.approved) {
                window.location.assign(config.homeUrl);
                return;
            }

            displayedState = result.state;
            renderState(displayedState);
            previewValid = true;
            showError("");

            if (previewStatus) {
                previewStatus.textContent = "Podgląd aktualny.";
            }
        } catch (error) {
            if (
                error.name === "AbortError" ||
                version !== previewVersion
            ) {
                return;
            }

            previewValid = false;
            showError(error.message);

            if (previewStatus) {
                previewStatus.textContent =
                    "Podgląd wymaga poprawienia lub odświeżenia.";
            }
        } finally {
            if (version === previewVersion) {
                updateButtons();
            }
        }
    }

    async function approve(repeatPrevious) {
        if (busy || !form) return;

        if (
            repeatPrevious &&
            signature() !== originalSignature &&
            !window.confirm(
                "Wprowadzone zmiany zostaną odrzucone. " +
                "Zachowane zostaną stawki podatkowe i proporcje " +
                "wydatków z poprzedniego okresu. " +
                "Czy chcesz kontynuować?"
            )
        ) {
            return;
        }

        let plan;

        try {
            plan = repeatPrevious
                ? { repeat_previous: true }
                : readPlan();
        } catch (error) {
            showError(error.message);
            return;
        }

        const previouslyDisplayedBasis = displayedState?.basis_token;

        cancelPreview();
        setBusy(true);
        showError("");

        let navigating = false;

        try {
            const preview = await requestJson(
                config.previewUrl,
                plan
            );

            if (preview.state.approved) {
                navigating = true;
                window.location.assign(config.homeUrl);
                return;
            }

            const freshState = preview.state;

            if (
                !repeatPrevious &&
                previouslyDisplayedBasis !== freshState.basis_token
            ) {
                displayedState = freshState;
                renderState(freshState);
                previewValid = true;

                throw new Error(
                    "Dane państwa, rezerwa lub półrocze zmieniły się. " +
                    "Sprawdź nowy podgląd i ponownie zatwierdź budżet."
                );
            }

            const result = await requestJson(config.approveUrl, {
                ...plan,
                repeat_previous: repeatPrevious,
                year: freshState.year,
                period: freshState.period,
                basis_token: freshState.basis_token
            });

            navigating = true;
            window.location.assign(result.redirect_url);
        } catch (error) {
            showError(error.message);

            if (error.status === 409) {
                previewValid = false;

                if (previewStatus) {
                    previewStatus.textContent =
                        "Stan finansów zmienił się. Odśwież stronę.";
                }
            }
        } finally {
            if (!navigating) setBusy(false);
        }
    }

    if (displayedState && form) {
        renderState(displayedState);

        if (!displayedState.approved) {
            form.addEventListener("input", () => {
                cancelPreview();
                previewValid = false;
                updateButtons();

                try {
                    readPlan();
                    showError("");

                    if (previewStatus) {
                        previewStatus.textContent =
                            "Zmiany oczekują na przeliczenie.";
                    }

                    debounceTimer = setTimeout(refreshPreview, 300);
                } catch (error) {
                    showError(error.message);
                }
            });

            form.addEventListener("submit", event => {
                event.preventDefault();

                if (!form.reportValidity() || !previewValid) return;
                approve(false);
            });

            repeatButton?.addEventListener("click", () => approve(true));

            if (previewStatus) {
                previewStatus.textContent = "Podgląd aktualny.";
            }
        }
    }

    root.querySelector("[data-finance-reload]")?.addEventListener(
        "click",
        () => window.location.reload()
    );

    const modal = document.getElementById("finance-modal");

    if (config.required && modal) {
        modal.addEventListener("cancel", event => {
            event.preventDefault();
        });

        modal.showModal();
        document.body.classList.add("finance-modal-open");

        modal.scrollTop = 0;
        modal.querySelector("input, button")?.focus({
            preventScroll: true
        });
    }

    function renderNotifications() {
        const container = root.querySelector(
            "[data-finance-notifications]"
        );

        if (!container) return;

        for (const notification of config.notifications || []) {
            const element = document.createElement("p");
            element.className = "finance-notice";
            element.textContent = notification.message;
            container.append(element);
        }
    }

    let acknowledging = false;

    async function acknowledgeNotifications() {
        if (document.hidden || acknowledging) return;
        acknowledging = true;

        for (const notification of config.notifications || []) {
            if (notification.acknowledged) continue;

            const url = config.notificationUrl.replace(
                "/0/",
                `/${notification.id}/`
            );

            try {
                await requestJson(url, {});
                notification.acknowledged = true;
            } catch (error) {
                console.error(
                    "Nie zapisano wyświetlenia powiadomienia:",
                    error
                );
            }
        }

        acknowledging = false;
    }

    renderNotifications();

    requestAnimationFrame(() => {
        requestAnimationFrame(acknowledgeNotifications);
    });

    document.addEventListener(
        "visibilitychange",
        acknowledgeNotifications
    );

    function addHistoryMetric(container, label, value) {
        const paragraph = document.createElement("p");
        const strong = document.createElement("strong");

        strong.textContent = label + ": ";
        paragraph.append(strong, document.createTextNode(value));
        container.append(paragraph);
    }

    const historyButtons = [
        ...document.querySelectorAll("[data-finance-history]")
    ];
    let activeHistoryButton = null;
    let historyRequestVersion = 0;

    function closeHistory() {
        historyRequestVersion += 1;

        const section = document.querySelector("[data-finance-history-detail]");
        if (section) section.hidden = true;

        historyButtons.forEach(button => {
            button.textContent = "Pokaż plan";
            button.setAttribute("aria-expanded", "false");
            button.disabled = false;
        });

        activeHistoryButton = null;
    }

    historyButtons.forEach(button => {
        button.setAttribute("aria-expanded", "false");
        button.setAttribute("aria-controls", "finance-history-detail");

        button.addEventListener("click", async () => {
            if (activeHistoryButton === button) {
                closeHistory();
                return;
            }

            closeHistory();
            activeHistoryButton = button;

            const version = historyRequestVersion;
            const section = document.querySelector("[data-finance-history-detail]");
            const container = document.querySelector("[data-finance-history-content]");

            button.disabled = true;
            button.textContent = "Ładowanie…";

            try {
                const id = button.dataset.financeHistory;
                const url = config.historyUrl.replace(/0$/, id);
                const result = await requestJson(url);

                // Użytkownik mógł w międzyczasie otworzyć inny plan.
                if (version !== historyRequestVersion) return;

                const state = result.state;
                container.replaceChildren();

                addHistoryMetric(
                    container,
                    "Okres",
                    `${state.year} / ${state.period === 1 ? "I" : "II"}`
                );
                addHistoryMetric(container, "Podatek ogólny", decimalText(state.pit_rate) + "%");

                addHistoryMetric(container, "Transza", moneyText(state.tax_total));
                addHistoryMetric(
                    container, "Rezerwa początkowa",
                    moneyText(state.opening_reserve)
                );
                addHistoryMetric(
                    container, "Dostępne środki",
                    moneyText(state.budget_total)
                );
                addHistoryMetric(
                    container, "Rezerwa końcowa",
                    moneyText(state.closing_reserve)
                );

                const chart = document.createElement("div");
                renderBudgetBar(chart, state);
                container.append(chart);

                section.hidden = false;
                button.textContent = "Ukryj plan";
                button.setAttribute("aria-expanded", "true");
                section.scrollIntoView({ block: "nearest", behavior: "smooth" });
            } catch (error) {
                if (version !== historyRequestVersion) return;
                closeHistory();
                showError(error.message);
            } finally {
                if (version === historyRequestVersion) button.disabled = false;
            }
        });
    });

    // Formatowanie kwot w tabeli historii.
    document.querySelectorAll("[data-finance-history-money]").forEach(element => {
        element.textContent = moneyText(element.dataset.financeHistoryMoney);
    });


    const transferForm=root.querySelector('[data-finance-transfer]');
    if(transferForm){
        let requestId=null,requestPayload=null;
        const source=transferForm.elements.source,destination=transferForm.elements.destination,amount=transferForm.elements.amount;
        const available=transferForm.querySelector('[data-transfer-available]'),status=transferForm.querySelector('[data-transfer-status]');
        function updateAvailable(){available.textContent='Pozostało w sektorze źródłowym: '+moneyText(displayedState.balances?.[source.value]?.remaining);}
        const transferError=transferForm.querySelector('[data-transfer-error]');
        function showTransferError(message){if(!transferError)return;transferError.textContent=message||'';transferError.hidden=!message;}
        function trustMessage(trust){return 'Społeczeństwo nie ufa władzy wystarczająco ('+(trust??'—')+'/100), by pozwolić na swobodne modyfikowanie budżetu i przesuwanie środków między sektorami.';}
        transferForm.addEventListener('input',()=>{requestId=null;requestPayload=null;status.textContent='';showTransferError('');updateAvailable();});
        transferForm.addEventListener('submit',async event=>{
            event.preventDefault();showError('');status.textContent='';showTransferError('');
            if(source.value===destination.value){showError('Wybierz dwa różne sektory budżetu.');return;}
            // Sector-to-sector transfers need public trust above the threshold; reserve operations stay open.
            if(displayedState.sector_transfers_allowed===false&&source.value!=='reserve'&&destination.value!=='reserve'){showTransferError(trustMessage(displayedState.public_trust));return;}
            const payload={budget_id:displayedState.budget_id,source:source.value,destination:destination.value,amount:window.GameMoney.fromBillions(amount.value)};
            const signature=JSON.stringify(payload);
            if(requestPayload!==signature){requestId=crypto.randomUUID?crypto.randomUUID():'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=crypto.getRandomValues(new Uint8Array(1))[0]&15;return (c==='x'?r:(r&3)|8).toString(16);});requestPayload=signature;}
            const button=transferForm.querySelector('button[type="submit"]');button.disabled=true;
            try{
                const result=await requestJson(config.transferUrl,{...payload,request_id:requestId});
                displayedState=result.state;renderState(displayedState);updateAvailable();
                status.textContent='Przesunięcie zapisane. Salda sektorów zostały zaktualizowane.';
                requestId=null;requestPayload=null;amount.value='';
            }catch(error){if(/nie ufa władzy/.test(error.message||''))showTransferError(error.message);else showError(error.message);}
            finally{button.disabled=false;}
        });
        updateAvailable();
    }

    updateButtons();
})();