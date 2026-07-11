# Design QA — Story Agent UI v1

- Source visual truth: `F:\Codex\story\docs\ui\story-planning-selected-v1.png`
- Implementation screenshot: `F:\Codex\story\apps\web\test-results\planning-1440-final.png`
- Responsive screenshot: `F:\Codex\story\apps\web\test-results\planning-1280-final.png`
- Combined comparison: `F:\Codex\story\apps\web\test-results\design-qa-comparison-final.png`
- Viewports: 1440 × 1024 and 1280 × 800
- State: story planning page, dark theme, selected “首次直面纸人”, pending AI change proposal

## Findings

No actionable P0/P1/P2 differences remain.

- Fonts and typography: bundled Noto Sans SC Variable and Noto Serif SC reproduce the source hierarchy; display titles, compact labels and table text remain legible at both target viewports.
- Spacing and layout rhythm: the sidebar, top status bar, central planning canvas, fixed status footer and 374px AI panel preserve the source three-column composition. At 1280px the central route remains scrollable without horizontal overflow.
- Colors and tokens: midnight navy surfaces, warm-gold selection, indigo AI accents and green/amber/red semantic states match the selected direction and meet the intended hierarchy.
- Image quality and asset fidelity: the compass identity and user portrait are project-local raster assets generated for the selected art direction; all UI icons come from one Phosphor icon family. No placeholder, emoji, handcrafted SVG or CSS illustration substitutes remain.
- Copy and content: visible Chinese planning, contract, foreshadow and AI-impact content is coherent and matches the product scenario.
- Accessibility and interaction: semantic navigation, headings, regions, labels, focus rings and reduced-motion handling are present. The AI panel stays available on every route and can be collapsed.

## Intentional Differences

- The source mock displays chapter 22 as if already applied. The implementation intentionally begins at chapter 18 and renders chapter 22 as a pending proposal, so the accept/reject/undo workflow can be demonstrated without silently changing author data.
- The implementation expands the source’s single summary diff into three selectable field operations, satisfying the reviewed-change requirement while retaining the same visual hierarchy.

## Comparison History

### Iteration 1

- [P2] Sidebar navigation rendered with browser-default purple underlines because the router callback was serialized into the `class` attribute.
- Fix: replaced callback class resolution with explicit pathname matching while keeping semantic links.
- Post-fix evidence: `planning-1440-final.png` and `design-qa-comparison-final.png` show gray inactive navigation and warm-gold selected navigation with no underlines.

### Iteration 2

- [P2] AI composer was materially shorter than the source and left excessive unused vertical space.
- Fix: increased the composer’s default writing area while retaining a fixed lower control position.
- Post-fix evidence: `planning-1440-final.png` shows a source-proportional composer and unchanged access to proposal actions.

## Browser Verification

- Primary interactions tested: module navigation, AI proposal acceptance, undo, invalid direct edit, valid direct edit, reload persistence, panel availability.
- 1440 × 1024: body and route horizontal overflow both absent; AI panel width 374px.
- 1280 × 800: body and route horizontal overflow both absent; AI panel width 374px; sidebar reduces to 94px.
- Browser console errors and warnings checked: none.
- Automated checks: production build passed; 5 unit tests passed; 4 Playwright tests passed across both target viewports.

## Follow-up Polish

- [P3] Fine-tune small-text optical weight after testing on the final Windows WebView2 renderer.
- [P3] Add hover tooltips to dense timeline markers when the backend supplies stable marker identifiers.

final result: passed
