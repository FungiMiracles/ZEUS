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

    // 13 Nov 2026: wykres kołowy jak na lewym pasku — te same kolory sektorów (game/sidebar.py SECTOR_COLORS).
    const sectorColors = {
        administration: "#7fa7d9", infrastructure: "#f0b35a", armed_forces: "#d9665b",
        social_policy: "#9b7fd1", environment: "#5fbf8a", health: "#e889b5",
        education: "#5ec3d6", research: "#c9d35a", security_services: "#8e9bb0",
        healthcare: "#e889b5", reserve: "#f2e6c9"
    };
    const fallbackColors = ["#7fa7d9", "#f0b35a", "#d9665b", "#9b7fd1", "#5fbf8a", "#e889b5", "#5ec3d6", "#c9d35a", "#8e9bb0", "#e07fdc", "#f2e6c9"];
    const svgNS = "http://www.w3.org/2000/svg";

    // 13 Nov 2026: bez tooltipa nad wykresem (zasłaniał legendę) — „Pozostało do wykorzystania” jest w legendzie.

    function slicePath(cx, cy, r, ri, start, end) {
        const point = (radius, angle) => [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
        const large = end - start > Math.PI ? 1 : 0;
        const [x1, y1] = point(r, start), [x2, y2] = point(r, end), [x3, y3] = point(ri, end), [x4, y4] = point(ri, start);
        const f = value => value.toFixed(2);
        return `M${f(x1)} ${f(y1)}A${f(r)} ${f(r)} 0 ${large} 1 ${f(x2)} ${f(y2)}L${f(x3)} ${f(y3)}A${f(ri)} ${f(ri)} 0 ${large} 0 ${f(x4)} ${f(y4)}Z`;
    }

    // Dokładna suma kwot dziesiętnych (tekst z serwera) przez BigInt.
    function sumDecimals(values) {
        const parts = values.map(decimalParts).filter(Boolean);
        const scale = parts.reduce((max, part) => part.scale > max ? part.scale : max, 1n);
        const sum = parts.reduce((acc, part) => acc + part.value * (scale / part.scale), 0n);
        const digits = scale.toString().length - 1;
        if (!digits) return sum.toString();
        const negative = sum < 0n, abs = negative ? -sum : sum;
        return `${negative ? "-" : ""}${abs / scale}.${(abs % scale).toString().padStart(digits, "0")}`;
    }

    function renderBudgetBar(container, state) {
        container.replaceChildren();

        // 13 Nov 2026: po zatwierdzeniu wykres pokazuje bieżące środki sektorów (plan po przesunięciach,
        // wpływach i korektach administratora, np. zmianie rezerwy), a nie pierwotny plan.
        const current = Boolean(state.approved && state.balances);
        const amountFor = code => current
            ? (state.balances?.[code]?.allocated ?? "0")
            : (state.allocations?.[code] ?? "0");
        const totalAmount = current
            ? sumDecimals(config.categories.map(category => amountFor(category.code)).filter(value => (decimalParts(value)?.value ?? 0n) > 0n))
            : state.budget_total;
        const total = decimalParts(totalAmount);
        const items = [];
        config.categories.forEach((category, index) => {
            const amount = amountFor(category.code);
            const parts = decimalParts(amount);
            if (!parts || parts.value <= 0n) return;
            // Waga służy wyłącznie geometrii wykresu; kwoty i procenty liczymy dokładnie przez BigInt.
            const weight = total && total.value > 0n
                ? Number(parts.value * total.scale) / Number(parts.scale * total.value)
                : 0;
            items.push({
                category, amount, weight,
                color: sectorColors[category.code] || fallbackColors[index % fallbackColors.length],
                percentage: allocationPercentage(amount, totalAmount),
                remaining: state.balances?.[category.code]?.remaining
            });
        });

        if (!items.length) {
            const empty = document.createElement("p");
            empty.textContent = "Brak środków do podziału.";
            container.append(empty);
            return;
        }

        const wrapper = document.createElement("div");
        wrapper.className = "finance-pie-chart";

        const pie = document.createElement("div");
        pie.className = "finance-pie";
        const svg = document.createElementNS(svgNS, "svg");
        svg.setAttribute("viewBox", "0 0 200 200");
        svg.setAttribute("role", "img");
        svg.setAttribute("aria-label", "Podział dostępnych środków według sektorów");

        // 13 Nov 2026: najechanie na wycinek podświetla wiersz legendy i odwrotnie.
        function highlight(item, on) {
            item.path?.classList.toggle("is-active", on);
            item.entry?.classList.toggle("is-active", on);
            wrapper.classList.toggle("has-active", on);
        }
        const weightSum = items.reduce((sum, item) => sum + item.weight, 0) || 1;
        let angle = -Math.PI / 2;
        items.forEach(item => {
            let share = item.weight / weightSum;
            if (items.length === 1) share = 0.99999;
            const end = angle + share * 2 * Math.PI;
            const path = document.createElementNS(svgNS, "path");
            path.setAttribute("d", slicePath(100, 100, 97, 97 * 0.56, angle, end));
            path.setAttribute("fill", item.color);
            path.setAttribute("class", "finance-pie-slice");
            path.setAttribute("tabindex", "0");
            const description = `${item.category.name}: ${moneyText(item.amount)} · ${item.percentage}%`
                + (item.remaining !== undefined ? ` · pozostało do wykorzystania: ${moneyText(item.remaining)}` : "");
            path.setAttribute("aria-label", description);
            item.path = path;
            const show = () => highlight(item, true);
            const hide = () => highlight(item, false);
            path.addEventListener("mouseenter", show);
            path.addEventListener("focus", show);
            path.addEventListener("mouseleave", hide);
            path.addEventListener("blur", hide);
            svg.append(path);
            angle = end;
        });

        const center = document.createElement("div");
        center.className = "finance-pie-center";
        const centerLabel = document.createElement("span");
        centerLabel.textContent = current ? "Aktualnie" : "Do podziału";
        const centerValue = document.createElement("strong");
        centerValue.textContent = moneyText(totalAmount);
        center.append(centerLabel, centerValue);
        pie.append(svg, center);

        const legend = document.createElement("ul");
        legend.className = "finance-pie-legend";
        items.forEach(item => {
            const entry = document.createElement("li");
            const dot = document.createElement("span");
            dot.className = "finance-budget-dot";
            dot.style.backgroundColor = item.color;
            const name = document.createElement("span");
            name.className = "finance-pie-name";
            name.textContent = item.category.name;
            const value = document.createElement("span");
            value.className = "finance-pie-value";
            value.textContent = `${moneyText(item.amount)} · ${item.percentage}%`;
            entry.append(dot, name, value);
            if (item.remaining !== undefined) {
                const remaining = document.createElement("span");
                remaining.className = "finance-pie-remaining";
                const remainingAmount = document.createElement("span");
                remainingAmount.className = "finance-pie-remaining-amount";
                remainingAmount.textContent = moneyText(item.remaining);
                remaining.append("Pozostało do wykorzystania: ", remainingAmount);
                entry.append(remaining);
            }
            item.entry = entry;
            entry.addEventListener("mouseenter", () => highlight(item, true));
            entry.addEventListener("mouseleave", () => highlight(item, false));
            legend.append(entry);
        });

        wrapper.append(pie, legend);
        container.append(wrapper);
    }

    // Tooltip „i” przy podatku ogólnym: najechanie / fokus (CSS) oraz dotknięcie (klasa is-open).
    root.querySelectorAll(".finance-info").forEach(info => {
        const button = info.querySelector("button");
        const close = () => { info.classList.remove("is-open"); button.setAttribute("aria-expanded", "false"); };
        button.addEventListener("click", () => {
            const open = info.classList.toggle("is-open");
            button.setAttribute("aria-expanded", String(open));
            if (!open) button.blur();
        });
        info.addEventListener("keydown", event => { if (event.key === "Escape") { close(); button.focus(); } });
        document.addEventListener("click", event => { if (!info.contains(event.target)) { close(); if (document.activeElement === button) button.blur(); } });
    });

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
    // 16 Nov 2026: środki na walkę z przestępczością (kwota w MLD, wysyłana w ROI).
    function crimeAmount(value) {
        try { return benefitAmount(value); }
        catch { throw Error('Podaj nieujemną kwotę na walkę z przestępczością w MLD.'); }
    }
    const crimeInput=form?.querySelector('[data-crime-funding]');
    // 25 Nov 2026: domyślnie kwoty oczekiwane przez społeczeństwo (świadczenia i walka z przestępczością) — gracz może je zmienić.
    // 25 Nov 2026: kwota w MLD z dwoma miejscami po przecinku, zaokrąglona w górę (0,01 MLD = 10 mln ROI = 10^9 groszy).
    const billionsInput=value=>{
        const cents=benefitCents(value), unit=1000000000n;
        const hundredths=(cents+unit-1n)/unit;
        const fraction=String(hundredths%100n).padStart(2,'0').replace(/0+$/,'');
        return `${hundredths/100n}${fraction ? '.'+fraction : ''}`;
    };
    if(crimeInput && config.state && !config.state.approved) {
        const initial=config.state.crime?.expected ?? config.state.crime?.previous_paid;
        if(initial!=null) crimeInput.value=billionsInput(initial);
    }
    if(form && config.state && !config.state.approved && config.state.benefits?.expected) {
        form.querySelectorAll('[data-benefit]').forEach(input=>{
            const expected=config.state.benefits.expected[input.dataset.benefit];
            if(expected!=null) input.value=billionsInput(expected);
        });
    }
    function amountCents(value) {
        const parts=decimalParts(value ?? '0');
        if(!parts) return 0n;
        return parts.value*100n/parts.scale;
    }
    function inputCents(input) {
        try { return benefitCents(benefitAmount(input.value)); } catch { return null; }
    }
    // Ostrzeżenie przy wierszu, gdy kwota przekracza przydział sektora (zatwierdzenie zostałoby odrzucone).
    function renderLimits(state) {
        if(!form || state.approved) return;
        const benefitWarning=form.querySelector('[data-benefits-warning]');
        if(benefitWarning) {
            const values=Array.from(form.querySelectorAll('[data-benefit]'),inputCents);
            const total=values.reduce((sum,value)=>sum+(value ?? 0n),0n);
            const available=amountCents(state.allocations?.social_policy);
            benefitWarning.hidden=!(total>available);
            benefitWarning.textContent=benefitWarning.hidden ? '' : `Świadczenia (${window.GameMoney.formatCents(total)}) przekraczają przydział polityki socjalnej i prorodzinnej (${moneyText(state.allocations?.social_policy)}). Zwiększ udział sektora albo zmniejsz kwoty.`;
        }
        const crimeWarning=form.querySelector('[data-crime-warning]');
        if(crimeWarning && crimeInput) {
            const value=inputCents(crimeInput) ?? 0n;
            const available=amountCents(state.allocations?.security_services);
            crimeWarning.hidden=!(value>available);
            crimeWarning.textContent=crimeWarning.hidden ? '' : `Środki na walkę z przestępczością (${window.GameMoney.formatCents(value)}) przekraczają przydział służb specjalnych i porządkowych (${moneyText(state.allocations?.security_services)}). Zwiększ udział sektora albo zmniejsz kwotę.`;
        }
    }
    function renderCrime(state) {
        const crime=state.crime;
        const info=form?.querySelector('[data-crime-expectations]');
        if(info) info.textContent=crime?.expected!=null
            ? `Oczekiwania społeczne na ${document.body.dataset.periodNom||'okres'}: ${moneyText(crime.expected)} (poziom przestępczości: ${crime.level ?? '—'}).`
            : 'Brak danych o ludności lub poziomie przestępczości — oczekiwania są niedostępne.';
        if(state.approved && crime?.paid!=null && crimeInput) crimeInput.value=benefitBillions(crime.paid);
        const result=form?.querySelector('[data-crime-result]');
        if(result) {
            result.textContent=crime?.settled && crime.old_level!=null
                ? `Rozliczono: przestępczość ${crime.new_level>crime.old_level?'wzrosła':crime.new_level<crime.old_level?'spadła':'nie zmieniła się'} (z ${crime.old_level} do ${crime.new_level}).`
                : (state.approved && crime ? 'Skutek finansowania zostanie rozliczony tydzień Entendy przed zatwierdzeniem kolejnego budżetu.' : '');
            result.hidden=!result.textContent;
        }
    }
    function renderState(state) {
        renderCrime(state);
        const benefits=state.benefits;
        const info=form.querySelector('[data-benefits-expectations]');
        const carried=(decimalParts(benefits?.carry_in || '0')?.value ?? 0n)>0n ? ` Przeniesione środki: ${moneyText(benefits.carry_in)}.` : '';
        if(info) info.textContent=benefits?.expected ? `Oczekiwania społeczne na ${document.body.dataset.periodNom||'okres'}: dzieci ${moneyText(benefits.expected.children)}, emerytury ${moneyText(benefits.expected.seniors)}, razem ${window.GameMoney.formatCents(benefitCents(benefits.expected.children)+benefitCents(benefits.expected.seniors))}.${carried}` : 'Brak struktury wieku ludności — oczekiwania świadczeń są niedostępne.';
        if(benefits?.paid) form.querySelectorAll('[data-benefit]').forEach(input=>{input.value=benefitBillions(benefits.paid[input.dataset.benefit]);});

        root.querySelectorAll("[data-value]").forEach(element => {
            const value = state[element.dataset.value];

            const text = element.hasAttribute("data-money")
                ? moneyText(value)
                : decimalText(value);
            element.textContent = element.hasAttribute("data-negative") && text !== "—" ? "−" + text : text;
        });

        root.querySelectorAll("[data-rail-income-row]").forEach(row => {
            row.hidden = !((decimalParts(state.rail_income || "0")?.value ?? 0n) > 0n);
        });

        root.querySelectorAll("[data-air-income-row]").forEach(row => {
            row.hidden = !((decimalParts(state.air_income || "0")?.value ?? 0n) > 0n);
        });

        // 18 Nov 2026: pozycja spłaty zaległości w MFW widoczna tylko, gdy MFW pobiera dług z tego budżetu.
        root.querySelectorAll("[data-imf-collection-row]").forEach(row => {
            row.hidden = !((decimalParts(state.imf_collection || "0")?.value ?? 0n) > 0n);
        });

        // 25 Nov 2026: utrzymanie wojska za poprzedni okres przy rekordzie sił zbrojnych — składniki, część z rezerwy, demobilizacja.
        root.querySelectorAll("[data-military-upkeep-row]").forEach(row => {
            const details = state.military_upkeep_details;
            const box = row.querySelector("[data-military-upkeep-details]");
            const due = details?.total || "0";
            const positive = value => (decimalParts(value || "0")?.value ?? 0n) > 0n;
            row.hidden = !details || (!positive(due) && !details.prepaid);
            if (!box) return;
            box.replaceChildren();
            if (row.hidden) return;
            const line = (text, className) => { const p = document.createElement("p"); if (className) p.className = className; p.textContent = text; box.append(p); return p; };
            if (details.prepaid && !positive(due)) {
                line("Utrzymanie wojska za poprzedni okres zostało opłacone według wcześniejszej zasady — w tym budżecie nic nie jest pobierane.");
                return;
            }
            line(`Utrzymanie wojska za poprzedni okres${state.dues_period ? ` (${state.dues_period})` : ""}: ${moneyText(due)}.`, "finance-upkeep-total");
            if (state.approved) {
                if (positive(details.from_reserve)) line(`W tym z rezerwy budżetowej: ${moneyText(details.from_reserve)}.`);
                const demobilized = Object.entries(details.demobilized || {}).filter(([, count]) => count);
                if (demobilized.length) line("Środków nie starczyło — przeprowadzono proporcjonalną demobilizację: "
                    + demobilized.map(([code, count]) => `${(details.items?.[code]?.label || code).toLowerCase()}: ${new Intl.NumberFormat("pl-PL").format(count)}`).join(", ") + ".", "finance-upkeep-warning");
            } else {
                const net = state.sector_net?.armed_forces;
                if ((decimalParts(net || "0")?.value ?? 0n) < 0n) {
                    const reserveLeft = decimalParts(state.reserve_after_dues || "0")?.value ?? 0n;
                    line(reserveLeft < 0n
                        ? "Przydział sił zbrojnych i rezerwa nie wystarczą na utrzymanie — po zatwierdzeniu nastąpi proporcjonalna demobilizacja: zwolnienie żołnierzy i likwidacja sprzętu."
                        : `Przydział sił zbrojnych nie wystarcza — brakujące ${moneyText(String(net).replace("-", ""))} pokryje rezerwa budżetowa.`, "finance-upkeep-warning");
                }
            }
            const list = document.createElement("details");
            const summary = document.createElement("summary");
            summary.textContent = "Składniki — wojsko posiadane w poprzednim okresie";
            list.append(summary);
            for (const item of Object.values(details.items || {})) {
                const entry = document.createElement("div");
                entry.className = "finance-upkeep-item";
                entry.textContent = item.count != null
                    ? `${item.label}: ${new Intl.NumberFormat("pl-PL").format(item.count)} × ${new Intl.NumberFormat("pl-PL", {maximumFractionDigits: 2}).format(Number(item.rate))} ROI = ${moneyText(item.amount)}`
                    : `${item.label}: ${moneyText(item.amount)}`;
                list.append(entry);
            }
            box.append(list);
        });

        // 25 Nov 2026: utrzymanie za poprzedni okres i kwota do dyspozycji sektora (ujemna — na czerwono).
        const isZero = value => (decimalParts(value || "0")?.value ?? 0n) === 0n;
        root.querySelectorAll("[data-due]").forEach(element => {
            const code = element.dataset.due;
            const value = code === "reserve" ? state.dues_from_reserve : state.sector_dues?.[code];
            element.textContent = value == null || isZero(value) ? "—" : "−" + moneyText(value);
            element.classList.toggle("finance-due-cell", !(value == null || isZero(value)));
        });
        root.querySelectorAll("[data-net]").forEach(element => {
            const code = element.dataset.net;
            const value = code === "reserve" ? state.reserve_after_dues : state.sector_net?.[code];
            element.textContent = moneyText(value ?? state.allocations?.[code]);
            element.classList.toggle("finance-negative", (decimalParts(value || "0")?.value ?? 0n) < 0n);
        });
        root.querySelectorAll("[data-dues-summary]").forEach(box => {
            box.replaceChildren();
            const total = state.dues_total;
            if (state.approved || !total || isZero(total)) { box.hidden = true; return; }
            const reserveLeft = decimalParts(state.reserve_after_dues || "0")?.value ?? 0n;
            const add = (text, className) => { const p = document.createElement("p"); if (className) p.className = className; p.textContent = text; box.append(p); };
            add(`Utrzymanie za poprzedni okres${state.dues_period ? ` (${state.dues_period})` : ""}: ${moneyText(total)} — pobierane z budżetów sektorów przy zatwierdzeniu.`);
            if (!isZero(state.dues_from_reserve)) {
                add(reserveLeft < 0n
                    ? `Brakuje ${moneyText(String(state.reserve_after_dues).replace("-", ""))} — rezerwa nie pokryje utrzymania. Wojsko zostanie częściowo zdemobilizowane, a obiekty miejskie stracą finansowanie.`
                    : `Z rezerwy budżetowej zostanie pokryte ${moneyText(state.dues_from_reserve)} (sektory na minusie).`, reserveLeft < 0n ? "finance-upkeep-warning" : "");
            }
            box.hidden = false;
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
        renderLimits(state);
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
            benefits: Object.fromEntries(Array.from(form.querySelectorAll("[data-benefit]")).map(input => [input.dataset.benefit,benefitAmount(input.value)])),
            ...(crimeInput ? { crime_funding: crimeAmount(crimeInput.value) } : {})
        };
    }

    function signature() {
        if (!form) return "";

        return JSON.stringify(
            Array.from(
                form.querySelectorAll(
                    ".finance-rate, .finance-share:not([readonly]), [data-benefit]:not([readonly]), [data-crime-funding]:not([readonly])"
                ),
                input => [
                    input.name || input.dataset.category || input.dataset.benefit || "crime_funding",
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
                    "Dane państwa, rezerwa lub okres budżetowy zmieniły się. " +
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
                renderLimits(displayedState);
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
        modal.querySelector("input:not([readonly]), .finance-actions button")?.focus({
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

    // 21 Nov 2026: szczegóły historycznego budżetu jako karty wskaźników (jak „Podstawy naliczenia”), nie zwykłe akapity.
    function addHistoryMetric(container, label, value) {
        let list = container.querySelector(":scope > .finance-history-metrics");
        if (!list) {
            list = document.createElement("dl");
            list.className = "finance-metrics finance-six-metrics finance-history-metrics";
            container.append(list);
        }
        const item = document.createElement("div");
        const term = document.createElement("dt");
        const detail = document.createElement("dd");
        term.textContent = label;
        detail.textContent = value;
        item.append(term, detail);
        list.append(item);
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
                chart.className = "finance-history-chart";
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


    const transferForm=document.querySelector('[data-finance-transfer]');
    if(transferForm){
        let requestId=null,requestPayload=null;
        const source=transferForm.elements.source,destination=transferForm.elements.destination,amount=transferForm.elements.amount;
        const available=transferForm.querySelector('[data-transfer-available]'),status=transferForm.querySelector('[data-transfer-status]');
        function updateAvailable(){available.textContent='Pozostało w sektorze źródłowym: '+moneyText(displayedState.balances?.[source.value]?.remaining);}
        const transferError=transferForm.querySelector('[data-transfer-error]');
        function showTransferError(message){if(!transferError)return;transferError.textContent=message||'';transferError.hidden=!message;}
        function trustMessage(trust){return 'Społeczeństwo nie ufa władzy wystarczająco ('+(trust??'—')+'/100), by pozwolić na swobodne modyfikowanie budżetu i przesuwanie środków między sektorami.';}
        transferForm.addEventListener('input',()=>{requestId=null;requestPayload=null;status.textContent='';showTransferError('');updateAvailable();});
        // 18 Nov 2026: kwota w MLN albo MLD (przełącznik), do 3 miejsc po przecinku; dokładne przeliczenie na ROI (BigInt).
        function transferAmount(){
            const unit=transferForm.querySelector('[name="amount_unit"]:checked')?.value||'MLD';
            const raw=String(amount.value||'').trim().replace(/[\s\u00a0]/g,'').replace(',','.');
            const m=/^(\d+)(?:\.(\d{1,3}))?$/.exec(raw);
            if(!m)throw new Error('Podaj kwotę w '+unit+', np. 250 albo 1,5 (najwyżej 3 miejsca po przecinku).');
            const scale=unit==='MLN'?1000000n:1000000000n;
            const value=(BigInt(m[1])*1000n+BigInt((m[2]||'').padEnd(3,'0')))*scale/1000n;
            if(value<1000000n)throw new Error('Najmniejsza kwota przesunięcia to 1 MLN ROI.');
            return value.toString();
        }
        transferForm.addEventListener('submit',async event=>{
            event.preventDefault();showError('');status.textContent='';showTransferError('');
            if(source.value===destination.value){showError('Wybierz dwa różne sektory budżetu.');return;}
            // Sector-to-sector transfers need public trust above the threshold; reserve operations stay open.
            if(displayedState.sector_transfers_allowed===false&&source.value!=='reserve'&&destination.value!=='reserve'&&!(destination.value==='armed_forces'&&displayedState.defense_transfers_allowed)){showTransferError(trustMessage(displayedState.public_trust));return;}
            let roi;try{roi=transferAmount();}catch(error){showError(error.message);return;}
            const payload={budget_id:displayedState.budget_id,source:source.value,destination:destination.value,amount:roi};
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