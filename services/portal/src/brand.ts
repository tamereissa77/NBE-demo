// The active brand pack (brand/brand.json), bundled at build time. Assets in brand/ are served at /
// (vite publicDir): /logo.png, /mark.png, /theme.css. brand/ is written by `make customer NAME=<customer>`
// (scripts/apply_customer.py) from customers/<name>/ and the country's portal locale.
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
  agentName?: { en: string; ar: string };  // D4's name on the phone mock-up (default: "<short> Virtual Agent")
  locale: {
    code?: string;                              // EG, SA, AE, MA
    country: { en: string; ar: string };
    currency: { en: string; ar: string };
    nationalId?: { en: string; ar: string };    // the ID number's name (D1)
    dialect: { code: string; en: string; ar: string };
    d4Script: { en: string[]; ar: string[] };   // scripted demo turns; "{code}" = the OTP
  };
}

export const BRAND: Brand = brandJson;
export const LOGO = "/logo.png";
export const MARK = "/mark.png";
