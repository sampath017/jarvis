# Jarvis eagle logo

Selected direction: K — Wing, refined at the user's request into a simple eagle with two outstretched wings. The app uses a flat blue silhouette with two broad feather tiers per wing and a small central head/body.

- Editable source: `../../mobile/assets/icon/jarvis-mark.svg`
- Brand metadata: `../../mobile/assets/brand.json`
- Transparent Flutter asset: `../../mobile/assets/icon/app_logo.png` (512 × 512)
- Preview on the app background: `eagle-preview.png`
- Android adaptive foreground: `../../mobile/android/app/src/main/res/drawable/ic_jarvis_foreground.xml`
- Legacy launcher PNG sizes: 48, 72, 96, 144, and 192 pixels.

The adaptive foreground retains its 0.64 scale to keep the wings inside the icon mask. Existing launcher and splash references consume the updated assets.

## Concept generation

The built-in image generation tool produced `eagle-concept.png` from K. The final SVG was then simplified into a solid, clean path and rasterized for app assets.

Prompt:

Use case: logo-brand. Edit target: the attached K — WING concept. Create the final simple Jarvis app logo as an abstract EAGLE WITH TWO WINGS. Preserve the selected concept's crisp angular style and periwinkle blue color, but replace its single wing with a symmetrical pair of outstretched wings joined to a tiny central eagle body. Wings sweep upward toward the outer tips. Each wing has only TWO broad geometric feather tiers. One small central downward tapered body and tiny angular head imply an eagle without illustrative details. A single compact cohesive silhouette with bold readable negative-space cuts. Extremely simple, flat solid fill #8AB4F8, clean vector-like edges, legible at 24px. Center the complete eagle on a square TRANSPARENT canvas, entire eagle fits comfortably within the central 62 percent of the canvas with generous equal padding for Android icon masks. No wording, no K caption, no letters, no border, no background panel, no gradients, no shadows, no 3D, no texture, no eyes, no claws, no detailed feathers, no crest or shield, no stars, no asterisk, no sunburst. Use an original restrained geometric eagle, not a sports mascot or an existing brand emblem.

