// Django's "Add another" fires `formset:added` on a cloned row whose inline script never runs, and
// django-tomselect does not listen for that event, so the row's control is initialised here (FS-011).
(function () {
    "use strict";

    // The last `-<digits>-` segment is the row being added: a nested inline id such as
    // `id_orders-0-items-1-product` holds two, and the template registered for the inner row is `__prefix__`.
    function templateRowId(rowId) {
        return rowId.replace(/-\d+-(?![\s\S]*-\d+-)/, "-__prefix__-");
    }

    // The clone carries a rendered `.ts-wrapper` with duplicate element ids and no TomSelect instance,
    // which initialize()'s own destroy step cannot reach. A live instance's wrapper is left alone.
    function discardClonedControl(select) {
        var live = select.tomselect ? select.tomselect.wrapper : null;
        var parent = select.parentElement;
        if (!parent) {
            return;
        }
        parent.querySelectorAll(":scope > .ts-wrapper").forEach(function (wrapper) {
            if (wrapper !== live) {
                wrapper.remove();
            }
        });
    }

    function initialiseRow(row) {
        if (!(row instanceof HTMLElement) || !window.djangoTomSelect) {
            return;
        }
        row.querySelectorAll("select[data-tomselect]").forEach(function (select) {
            var config = window.djangoTomSelect.configs.get(templateRowId(select.id));
            if (!config) {
                return;
            }
            discardClonedControl(select);
            window.djangoTomSelect.initialize(select, config);
        });
    }

    document.addEventListener("formset:added", function (event) {
        initialiseRow(event.target);
    });
})();
