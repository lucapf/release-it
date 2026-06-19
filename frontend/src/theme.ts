import { Card, createTheme, Modal } from "@mantine/core";

// Centralised design language for ReleaseIT. Beyond the indigo primary we tune
// typography, default surfaces and component defaults so the app reads as a
// deliberately-designed product rather than stock Mantine.
export const theme = createTheme({
  primaryColor: "indigo",
  primaryShade: { light: 6, dark: 8 },
  defaultRadius: "md",
  fontFamily:
    "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
  headings: {
    fontFamily:
      "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
    fontWeight: "700",
  },
  // A softer, layered shadow scale so cards lift off the tinted page background.
  shadows: {
    xs: "0 1px 2px rgba(15, 23, 42, 0.04)",
    sm: "0 1px 3px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.04)",
    md: "0 4px 12px rgba(15, 23, 42, 0.06), 0 2px 4px rgba(15, 23, 42, 0.04)",
  },
  components: {
    Card: Card.extend({
      defaultProps: { withBorder: true, shadow: "sm", radius: "md" },
    }),
    Modal: Modal.extend({
      defaultProps: { radius: "md", centered: true, overlayProps: { blur: 2 } },
    }),
  },
});
