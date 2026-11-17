import React from 'react';
import { Link } from 'react-router-dom';
import { Info } from 'lucide-react';
import { useLang } from '../lang.jsx';
import { SITE } from '../site.config.js';
import Reveal from '../components/Reveal.jsx';
import { PageHead } from '../components/Bits.jsx';

// Privacy and Terms are written from how Recat Studio really works today (retention, data, providers, payments).
// English only on purpose: have a lawyer review them (and add a governing law) before relying on them.
const K = SITE.keepDays;
const Contact = () => <Link to="/contact">Contact page</Link>;

const PRIVACY = [
  { h: 'Who this applies to', body: (<>
    <p>This policy explains what {SITE.name} (“we”, “us”) collects when you use our website and the Recat Studio app, why, who else sees it, and how long we keep it. We wrote it in plain language and describe how the service works today.</p>
  </>) },
  { h: 'What we collect', body: (<>
    <ul>
      <li><strong>Account details.</strong> Your login name or email, and your password in scrambled (hashed) form. We cannot read your password. Our team creates accounts for a set number of months, so we also keep the end date.</li>
      <li><strong>Your videos and what we make from them.</strong> The clip you upload (or the video our server fetches when you paste a RedNote or YouTube link), the speech we transcribe from it, the Burmese translation, the generated voice clips, the finished video, and the edits you make.</li>
      <li><strong>Choices you make.</strong> Voice, format, subtitle style, blur and logo settings, and the logo image you upload.</li>
      <li><strong>Usage records.</strong> The minutes each video used, when it ran, whether it finished or failed, and technical logs and error messages we need to fix problems.</li>
      <li><strong>Payments.</strong> When you top up minutes: the pack you chose, the amount, the note you type, and the payment slip image or PDF you upload. Slips can show bank details, so they are private and only our team can open them.</li>
      <li><strong>Reviews.</strong> If you rate a video: the stars and any text you write, together with the video’s technical details. Only our team can read reviews.</li>
      <li><strong>Device information.</strong> Your browser, device type, IP address and when each device last used your login. We use it to enforce one device at a time and to protect accounts.</li>
      <li><strong>Messages.</strong> What you send us through the Contact page or by email.</li>
    </ul>
    <p>We do not use advertising trackers and we do not sell your data.</p>
  </>) },
  { h: 'How we use it', body: (<>
    <ul>
      <li>To make your video: transcribe, translate, record the voice-over, draw subtitles and render the result.</li>
      <li>To run your account: allowances, bought minutes, one-device sign-in, support.</li>
      <li>To check payments by hand and prevent fraud or abuse.</li>
      <li>To fix problems and improve quality. Our team may open a video’s details, error and log when something fails or when you ask for help.</li>
      <li>To keep the service safe and to follow the law.</li>
    </ul>
  </>) },
  { h: 'Who we share it with', body: (<>
    <p>We use outside providers to run parts of the service. They receive only what is needed for that step:</p>
    <ul>
      <li><strong>AI providers (Google).</strong> The audio of your video and its text are sent to Google’s Gemini models to transcribe, translate and speak, and sometimes to Google Cloud Text-to-Speech. We use Google’s paid API. According to Google’s published terms, data sent through the paid API is not used to improve Google’s products.</li>
      <li><strong>Voice provider (Microsoft Azure).</strong> If you choose the Standard voice, the Burmese script text is sent to Microsoft Azure Speech to produce the audio.</li>
      <li><strong>Video sites.</strong> When you paste a link, our server downloads that video from the site (for example RedNote or YouTube). Nothing about your account is sent to them.</li>
      <li><strong>Hosting.</strong> Our servers are rented from a hosting company and are located in Japan.</li>
    </ul>
    <p>We may also share information if the law requires it, or to protect our users and service. We do not share it for advertising.</p>
  </>) },
  { h: 'How long we keep it', body: (<>
    <ul>
      <li><strong>Videos.</strong> Finished videos, the source clip and the voice clips used for editing are kept for {K} days, then deleted. If you made a video with “Render on my device”, a copy also stays in your own browser for {K} days.</li>
      <li><strong>Your list of videos</strong> (title, date, minutes) and usage records stay while your account exists.</li>
      <li><strong>Payments.</strong> Top-up requests and slips are kept as long as we need them for accounting and fraud checks.</li>
      <li><strong>Reviews</strong> may be kept after the video is deleted so we can learn from them.</li>
      <li><strong>Backups.</strong> We make nightly backups of our database and settings and keep them for 14 days. A deleted item can remain in a backup until that backup expires.</li>
    </ul>
  </>) },
  { h: 'Your choices', body: (<>
    <ul>
      <li>You can delete any of your videos at any time in “My videos”. This removes the copy on our server and the copy in your browser.</li>
      <li>You can ask us to delete your account. We then remove your account, videos, devices, top-up requests and slips. We keep a short record that the deletion happened.</li>
      <li>You can ask what we hold about you, or ask us to correct it.</li>
    </ul>
    <p>To use these choices, reach us through the <Contact />. Never send your password.</p>
  </>) },
  { h: 'Cookies and browser storage', body: (<>
    <p>We keep a sign-in token, your language choice, and small preferences (for example that you skipped a review) in your browser’s storage. Videos made on your device are stored in your browser’s own database for {K} days. These are needed to run the app; they are not used for advertising. You can clear them in your browser settings, but you will then be signed out. This website remembers only your language choice.</p>
  </>) },
  { h: 'Security', body: (<>
    <p>Connections use HTTPS. Passwords are stored hashed. Payment slips and finished videos are served only through private links that expire. Access to our admin tools is limited to our team. No system is perfectly secure, so please use a strong password and do not share your login.</p>
  </>) },
  { h: 'Children', body: (<>
    <p>Recat Studio is not meant for children. Accounts are created by our team for adults and for creators who are old enough to agree to our Terms where they live.</p>
  </>) },
  { h: 'Changes to this policy', body: (<>
    <p>If we change how we handle data, we will update this page and the date at the top. For big changes we will tell account holders.</p>
  </>) },
  { h: 'Contact', body: (<><p>Questions about privacy? Use the <Contact />.</p></>) },
];

const TERMS = [
  { h: 'Agreement', body: (<>
    <p>By using the {SITE.name} website or app you agree to these terms. If you do not agree, please do not use the service.</p>
  </>) },
  { h: 'What the service does', body: (<>
    <p>Recat Studio turns a video you provide into a version with a Burmese voice-over, subtitles and edits you choose. It uses AI to transcribe, translate and speak. It is a tool: you decide what to make and what to publish.</p>
  </>) },
  { h: 'Accounts', body: (<>
    <ul>
      <li>Accounts are created by our team for a set number of months. When that time ends, the account is suspended until it is renewed. Your videos and bought minutes are not deleted by suspension.</li>
      <li>Keep your login private. One login can be used on one device at a time; signing in on a new device signs out the oldest one.</li>
      <li>You are responsible for what happens under your login. Tell us at once if you think someone else is using it.</li>
      <li>We may suspend or close an account that breaks these terms.</li>
    </ul>
  </>) },
  { h: 'Your videos and your rights', body: (<>
    <ul>
      <li>You keep ownership of your videos and of what you make.</li>
      <li>You promise that you own each video you use, or have permission from the owner to copy, translate, dub and publish it, and that using it with Recat Studio does not break anyone’s rights or any law.</li>
      <li>You give us permission to process your videos, including sending the audio and text to our service providers, only to provide the service to you.</li>
      <li>Videos fetched from a link are fetched on your instruction. You are responsible for having the right to use them and for following the rules of the site they come from.</li>
    </ul>
  </>) },
  { h: 'What you must not do', body: (<>
    <ul>
      <li>Do not use the service for anything illegal, hateful, or that sexualises or harms children.</li>
      <li>Do not use videos or voices to impersonate or mislead people, or to harass anyone.</li>
      <li>Do not upload content you have no right to use, or malware.</li>
      <li>Do not try to break, overload or get around the limits of the service, or resell access without our written permission.</li>
    </ul>
  </>) },
  { h: 'Minutes and payments', body: (<>
    <ul>
      <li>Videos use minutes. Every account has a daily and monthly allowance. You can buy more minutes by top-up; bought minutes do not expire.</li>
      <li>Top-ups are paid by bank QR code. You upload the payment slip and our team adds the minutes after checking it. The price is shown in the app before you pay and can change; a change does not alter minutes you already own.</li>
      <li>A video’s minutes are used when it starts processing. If you cancel or it fails after it has started, the minutes are still used, because the processing already cost us money. A video that has not started can be cancelled at no cost. If something went wrong on our side, contact us and we will look at it; we may give minutes back.</li>
      <li>Editing a finished video does not use new minutes.</li>
      <li>If we notice repeated failed or cancelled videos, uploads may be paused for a few hours.</li>
    </ul>
  </>) },
  { h: 'AI results can be wrong', body: (<>
    <p>Translations, voices and subtitles are made by AI and can contain mistakes, mishear names, or sound unnatural. Check the result before you publish it. We do not promise that a result is accurate, suitable for your purpose, or free of other people’s rights.</p>
  </>) },
  { h: 'Availability and changes', body: (<>
    <p>We work to keep the service running, but we cannot promise it will always be available or fast. At busy times we may refuse new videos for a while. We may change, pause or stop features, and we may update these terms; the date at the top shows the latest version.</p>
  </>) },
  { h: 'Copyright and takedown', body: (<>
    <p>If you believe a video made with Recat Studio infringes your rights, tell us through the <Contact /> with the details. We will look into it and may remove content or suspend an account.</p>
  </>) },
  { h: 'Ending your use', body: (<>
    <p>You can stop using the service at any time and ask us to delete your account. We can suspend or end access if these terms are broken or the law requires it. Parts of these terms that should continue after that (for example about liability) do continue.</p>
  </>) },
  { h: 'Our responsibility', body: (<>
    <p>The service is provided “as is”. To the extent the law allows, we are not responsible for indirect or lost profits or content, and our responsibility for any claim is limited to the amount you paid us for the service in the 3 months before it. Nothing here limits rights you have by law that cannot be limited.</p>
  </>) },
  { h: 'Contact', body: (<><p>Questions about these terms? Use the <Contact />.</p></>) },
];

export default function Legal({ kind }) {
  const { lang } = useLang();
  const privacy = kind === 'privacy';
  const items = privacy ? PRIVACY : TERMS;
  return (
    <>
      <PageHead kicker="Legal" title={privacy ? 'Privacy Policy' : 'Terms of Use'}>
        {privacy ? 'What we collect, why, and how long we keep it.' : 'The rules for using Recat Studio.'}
      </PageHead>
      <section className="px-4 pb-20">
        <div className="mx-auto max-w-3xl">
          <Reveal className="rounded-[2rem] bg-white p-6 shadow-card sm:p-10">
            <div className="mb-2 text-sm text-ink-faint">Last updated: {SITE.updated}</div>
            {lang === 'my' && (
              <p className="mb-4 flex items-start gap-2 rounded-2xl bg-violet-50 p-3 text-sm text-violet-700">
                <Info size={18} className="mt-0.5 shrink-0" />
                <span lang="my">ဤစာမျက်နှာကို အင်္ဂလိပ်လိုသာ ရေးသားထားပါသည်။ မေးစရာရှိလျှင် ဆက်သွယ်ရန်စာမျက်နှာမှ မြန်မာလို မေးနိုင်ပါသည်။</span>
              </p>
            )}
            <div className="prose-recat">
              {items.map((s, i) => (<section key={s.h}><h2>{i + 1}. {s.h}</h2>{s.body}</section>))}
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
