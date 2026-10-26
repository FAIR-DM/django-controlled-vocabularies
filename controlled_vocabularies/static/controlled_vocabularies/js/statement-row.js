// A statement row on the vocabulary form: the value control and the language follow the kind of the
// predicate picked. Registered on alpine:init, so this file runs before Alpine does: a plain script in
// the body runs ahead of every deferred one.
(function () {
    "use strict";
    if (window.dcvStatementRow) {
        return;
    }
    window.dcvStatementRow = true;

    function kinds() {
        var script = document.getElementById("statement-predicate-kinds");
        return script ? JSON.parse(script.textContent) : {};
    }

    // django-tomselect starts a control on an added row from a debounced observer, which has been seen
    // to miss the first row added. Once it has had its turn, a row still without a live control gets one.
    var TOM_SELECT_GRACE = 1000;

    function ensureTomSelect(select) {
        var tom = window.djangoTomSelect;
        if (!tom || select.tomselect || !select.isConnected) {
            return;
        }
        var config = tom.configs.get(select.id) || tom.findSimilarConfig(select.id);
        if (config) {
            tom.initialize(select, config);
        }
    }

    document.addEventListener("alpine:init", function () {
        Alpine.data("dcvStatement", function () {
            return {
                predicate: "",
                known: kinds(),
                // A stored modified date that is not YYYY-MM-DD cannot fill a date input, so it is
                // edited as text rather than dropped on the next save.
                notADate: false,

                // A predicate the package does not list takes free text, like a literal.
                get kind() {
                    if (this.predicate === "dcterms:modified") {
                        return this.notADate ? "typed" : "date";
                    }
                    return this.known[this.predicate] || "literal";
                },

                init() {
                    var select = this.$el.querySelector("select[name$='-predicate']");
                    this.predicate = select.value;
                    var date = this.$el.querySelector("input[type=date]");
                    var text = this.$el.querySelector("input[type=text][name$='-value']");
                    this.notADate = Boolean(date && text && !date.value && text.value);
                    // Tom Select fires change on the select it replaces.
                    select.addEventListener("change", () => {
                        this.predicate = select.value;
                    });
                    setTimeout(() => ensureTomSelect(select), TOM_SELECT_GRACE);
                },
            };
        });
    });
})();
