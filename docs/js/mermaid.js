(function () {
    const sourceSelector = "pre.mermaid-source, div.mermaid-source";
    let renderIndex = 0;

    function currentTheme() {
        return document.body.getAttribute("data-md-color-scheme") === "slate"
            ? "dark"
            : "default";
    }

    function sourceText(block) {
        const code = block.querySelector("code");
        return (code ? code.textContent : block.textContent || "").trim();
    }

    async function renderBlock(block) {
        if (block.dataset.mermaidRendered === "true") {
            return;
        }
        block.dataset.mermaidRendered = "true";

        const source = sourceText(block);
        const target = document.createElement("div");
        target.className = "mermaid-diagram";

        try {
            const id = "mermaid-diagram-" + renderIndex++;
            const result = await window.mermaid.render(id, source);
            target.innerHTML = result.svg;
            if (result.bindFunctions) {
                result.bindFunctions(target);
            }
        } catch (error) {
            target.classList.add("mermaid-diagram--error");
            target.textContent = source;
            console.error("Mermaid render failed", error);
        }

        block.replaceWith(target);
    }

    function renderMermaid() {
        if (!window.mermaid) {
            return;
        }

        window.mermaid.initialize({
            startOnLoad: false,
            securityLevel: "strict",
            theme: currentTheme(),
        });

        document.querySelectorAll(sourceSelector).forEach((block) => {
            renderBlock(block);
        });
    }

    if (window.document$) {
        window.document$.subscribe(renderMermaid);
    } else {
        document.addEventListener("DOMContentLoaded", renderMermaid);
    }
})();
