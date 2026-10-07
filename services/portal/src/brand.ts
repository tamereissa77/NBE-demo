// The active brand pack (brand/brand.json), bundled at build time. Assets in brand/ are served at /
// (vite publicDir): /logo.png, /mark.png, /theme.css.
import brandJson from "../../../brand/brand.json";

export interface Brand {
  id: string;
  short: string;
  name: { en: string; ar: string };
  assistant: { en: string; ar: string };
  appTitle: { en: string; ar: string };
  website: string;
  heroTitle?: { en: string; ar: string };   // home banner title (default: the GB10 headline)
  heroChips?: boolean;                     // show the PoC / offline / synthetic chips on the home banner (default true)
  locale: {
    country: { en: string; ar: string };
    currency: { en: string; ar: string };
    dialect: { code: string; en: string; ar: string };
    d4Script: { en: string[]; ar: string[] };   // scripted demo turns; "{code}" = the OTP
  };
}

export const BRAND: Brand = brandJson;
export const LOGO = "/logo.png";
export const MARK = "/mark.png";
