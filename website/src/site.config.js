// The few facts that live outside the page text. Edit here, rebuild, done.
export const SITE = {
  name: 'Recat Studio',
  // The app people log in to (the same one that runs on movie-recap.bronicon.co).
  appUrl: 'https://movie-recap.bronicon.co',
  // PUBLIC contact details. An empty value hides that channel on the Contact page.
  // The contact form opens the visitor's email app addressed to `email`; with no email set the form explains how to reach us instead.
  contact: {
    email: 'info@trustedbrothers.co',      // e.g. 'hello@yourdomain.com'
    telegram: '',   // e.g. 'https://t.me/yourname'
    facebook: '',   // e.g. 'https://facebook.com/yourpage'
    phone: '',      // e.g. '+66 00 000 0000'
    hours: '',      // e.g. 'Mon-Sat, 9:00-18:00 (Thailand time)'
  },
  // Shown on the Pricing page. Keep in sync with admin Settings -> Pricing (the app always shows the current price).
  pricePerMinuteTHB: 5,
  packs: [30, 60, 100, 200],
  maxVideoMinutes: 10,
  keepDays: 14,
  updated: '16 November 2026',
};
