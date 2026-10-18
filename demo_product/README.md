# RefillHK demonstration product

Synthetic simulation — not real user research.

RefillHK is an invented Hong Kong household-cleaning refill service for SDG 12. These sites use local HTML, CSS and JavaScript only. They have no backend, payment, analytics, external assets or network API calls. Completing the form creates no real account or trial.

From the repository root, run each version in its own terminal:

```sh
python -m http.server 8101 --directory demo_product/v1
python -m http.server 8102 --directory demo_product/v2
```

Open http://localhost:8101 or http://localhost:8102. The shared task list is `demo_product/tasks.json`.

Version 1 intentionally has three usability flaws: plans use the vague navigation label “Options”; delivery areas appear only in the footer navigation; and the trial form has many fields with a “Proceed” button. Name, email and phone are required; all additional text fields are optional. The form validates locally before navigating to `welcome.html`.

Version 2 makes one pricing-discovery improvement: the home page displays the Basic plan price and the navigation label changes to “Pricing”. All other content, delivery navigation and form behavior are unchanged.

Task checks use page-body text or the actual URL. In version 1, “HK$268 per month” appears only on the plans page and “Kwun Tong” appears only on the delivery page. Welcome navigation occurs after valid form submission; direct navigation to that page is not evidence of filling the form.
