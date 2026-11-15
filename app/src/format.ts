const nf1 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const pct = (p: number) => `${Math.round(p * 100)}`;
export const pct1 = (p: number) => nf1.format(p * 100);
export const odds = (o: number) => nf2.format(o);
export const num1 = (x: number) => nf1.format(x);
export const signed = (x: number) => (x > 0 ? "+" : x < 0 ? "−" : "±") + nf1.format(Math.abs(x));

export const tipTime = (iso: string | null) =>
  iso
    ? new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" }).format(
        new Date(iso),
      )
    : "—";

export const longDate = (isoDate: string) =>
  new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" }).format(
    new Date(isoDate + "T12:00:00Z"),
  );

export const shortDate = (isoDate: string) =>
  new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(
    new Date(isoDate + "T12:00:00Z"),
  );
