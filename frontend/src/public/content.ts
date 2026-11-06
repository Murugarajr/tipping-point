export const categories = ["All workshops", "Clay", "Textiles", "Paper", "Print"] as const;
export type CategoryFilter = typeof categories[number];
export type Craft = "clay" | "thread" | "paper";

export interface ExampleWorkshop {
  id: string;
  source: "illustrative-example";
  title: string;
  category: Exclude<CategoryFilter, "All workshops">;
  craft: Craft;
  intro: string;
  priceMinor: number;
  duration: string;
  location: string;
  includes: string;
  takeaway: string;
}

// Editorial demonstration inputs, not provider offers or published campaign terms.
export const exampleWorkshops: readonly ExampleWorkshop[] = [
  {
    id: "a-little-clay", source: "illustrative-example",
    title: "A little clay, a little calm.", category: "Clay", craft: "clay",
    intro: "Slow down, get your hands into clay, and learn to shape a small pinch pot. A gentle introduction to making something entirely your own.",
    priceMinor: 4800, duration: "2 hours", location: "Example studio · London",
    includes: "Clay, shared tools and guided making",
    takeaway: "Explore pinching, shaping and surface texture. Firing and collection would need to be confirmed by a host before publication.",
  },
  {
    id: "make-your-mark", source: "illustrative-example",
    title: "Small stitches. Big possibilities.", category: "Textiles", craft: "thread",
    intro: "Find your rhythm with a needle and thread. Explore simple embroidery stitches and turn a little piece of fabric into a personal composition.",
    priceMinor: 3600, duration: "2.5 hours", location: "Example studio · Bristol",
    includes: "Practice fabric, thread and use of a hoop",
    takeaway: "Try a handful of beginner stitches and design a small embroidered sampler.",
  },
  {
    id: "pages-of-your-own", source: "illustrative-example",
    title: "A book with your name on it.", category: "Paper", craft: "paper",
    intro: "Fold, gather and stitch your way to a handmade notebook. Discover the quiet satisfaction of building a book from the first blank page.",
    priceMinor: 4200, duration: "3 hours", location: "Example studio · Manchester",
    includes: "Paper, cover stock and shared binding tools",
    takeaway: "Explore a simple stitched binding and take inspiration for your next sketchbook.",
  },
];

export function filterWorkshops(category: CategoryFilter) {
  return category === "All workshops" ? exampleWorkshops : exampleWorkshops.filter((workshop) => workshop.category === category);
}

export function findWorkshop(id: string | null) {
  return exampleWorkshops.find((workshop) => workshop.id === id);
}

export function formatPrice(minor: number) {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(minor / 100);
}

export const faqs = [
  ["Do I need an account?", "Not to explore. You can browse workshop information without signing in. The guest continuation form is currently a preview, not an active booking service. Hosts sign in separately."],
  ["What is a workshop’s tipping point?", "It is the first attendance level at which the approved cost assumptions can be covered. Materials bought in packs can change the costs at higher attendance, so the actual booked group still needs its own checks."],
  ["Am I charged immediately?", "No payments can be made through this preview. In the intended Sandbox booking flow, you approve a payment authorization rather than an immediate completed charge. A temporary hold may appear; authorization is not collection."],
  ["What happens if it cannot run?", "The intended flow releases open authorizations. If payments have already been collected during an unsuccessful settlement, they require a compensating refund process. Releases and refunds are not instantaneous; unresolved outcomes need review."],
  ["Can I use this as a host?", "The existing host workspace supports provisioned merchant accounts, workshop drafts, server-calculated cost previews and publication. Public registration, guest bookings and the complete payment journey are not enabled."],
  ["Is this currently a real-money service?", "No. Tipping Point is a PayPal Sandbox prototype. It does not accept real payments, and the example workshops on this site are not bookable inventory."],
] as const;
