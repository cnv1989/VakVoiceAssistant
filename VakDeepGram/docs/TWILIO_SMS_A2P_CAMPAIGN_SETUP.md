# Twilio SMS: A2P 10DLC Campaign Setup

To send SMS to US numbers from a **10DLC** (10-digit long code) number, US carriers require an approved **A2P** (Application-to-Person) campaign. This guide walks through getting that approval in Twilio.

> **Note:** If you only need one-time codes (OTP/2FA), consider [Twilio Verify](https://www.twilio.com/docs/verify) instead—it does not require A2P registration.  
> **Toll-free** and **short code** numbers are not part of A2P 10DLC; you can use them for US SMS without this process. See [comparison of number types](https://help.twilio.com/hc/en-us/articles/360038173654).

---

## No business (individual / hobbyist / sole proprietor)

If you don’t have a business or tax ID (no EIN, no Canadian Business Number), use **Sole Proprietor** registration. You need a **US or Canadian address** and **no business Tax ID**.

**Console:** [A2P Onboarding](https://console.twilio.com/us1/develop/sms/regulatory-compliance/a2p-onboarding)

### What you’ll need

- **US or Canadian address** (can be your personal address)
- **Personal mobile number** (US or Canadian; not from Twilio or another CPaaS). Twilio will send an OTP to this number during Brand registration. This number can be used for at most **3** Sole Proprietor Brand registrations with TCR (across all providers).
- **Email** (real, non-disposable; valid domain). Used at most **10** times for A2P Brand registrations with TCR.
- **Name** (first, last) — used as “Brand name” if you’re not using a business/DBA name.
- For **Campaign**: description of what you’ll send, how users opt in, 2 sample messages, and (if applicable) opt-in/opt-out/help keywords.

### Steps (Sole Proprietor)

1. **Create a Twilio Starter Profile**
   - On the Onboarding page, answer the questions: indicate you have a US/Canada address and that you do **not** have a business Tax ID (EIN/CBN).
   - When asked if you want to continue as Sole Proprietor, confirm **Yes**.
   - Enter: contact phone, country code, email, last name, first name, **Profile name** (your name or a name for this profile).
   - Add your **address** (US or Canada).
   - Review and **Submit for review**.

2. **Register your US A2P Brand (Sole Proprietor)**
   - On the same flow, **Register Brand**.
   - Enter: **Brand name** (your first + last name, or a business/DBA name), **mobile number** for OTP (US/Canadian mobile, not from a provider like Twilio), optional **business vertical**.
   - Agree to the one-time Brand fee and OTP consent, then **Register**.
   - **Complete the OTP** sent to your mobile within 24 hours. Brand approval is usually within a few minutes after OTP.

3. **Register your Campaign**
   - **Use case:** Sole Proprietor (only option for this Brand type).
   - **Messaging Service:** Create a new one (typical for sole prop) or select an existing one. A Sole Proprietor Campaign can have **only one** 10DLC number in the service.
   - **Campaign description:** Clear explanation of who sends, who receives, and why (e.g. “I send appointment reminders to people who signed up on my site”). Single words like “Marketing” are not enough.
   - **Message flow / opt-in:** How users consent (e.g. “Users opt-in on my website by entering their number and checking a box. Terms at example.com/terms, Privacy at example.com/privacy”). Consent cannot be obtained by sending an SMS to someone who hasn’t opted in.
   - **Sample messages:** At least 2 (each 20–1024 chars). Include your name or site; use `[brackets]` for variable parts; mention opt-out (e.g. “Text STOP to opt out”). If you only have one message type (e.g. OTP), you can duplicate it for the second sample.
   - **Opt-in/opt-out/help:** If users can text a keyword to opt in, add those keywords and the auto-reply. For opt-out/help, you can use Twilio’s default (recommended) or configure your own.
   - Submit; Campaign goes to **manual vetting** (can take **several weeks**).

4. **Add a 10DLC number to the Messaging Service**
   - Buy a **Local (10DLC)** number if you don’t have one: Phone Numbers → Manage → Buy a number.
   - Messaging → Services → open the Sole Proprietor Messaging Service → **Add Senders** → add your 10DLC number. Sole Proprietor Campaigns support **only one** 10DLC number.

After the Campaign status changes from **In Progress** to **VERIFIED**, you can send A2P SMS from that number via the Messaging Service.

**Sole Proprietor limits:** About 1,000 SMS/MMS segments per day to T-Mobile (~3,000 across US carriers). One Campaign per Brand; one 10DLC number per Campaign.

---

## 1. Choose your path (if you have a business)

| Your situation | Path | Console guide |
|----------------|------|----------------|
| **No business** (individual, hobbyist, no EIN) | Sole Proprietor Brand | See **“No business”** section above; [Sole Proprietor overview](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/direct-sole-proprietor-registration-overview) |
| **Business with EIN** (US) or **Canadian Business Number** | Direct Standard or Low-Volume Standard | [Direct Standard / Low-Volume onboarding](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/direct-standard-onboarding) |
| **Software company** building SMS for your customers | ISV | [ISV onboarding](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/onboarding-isv) |

- **Low-Volume Standard**: &lt; ~6k segments/day, lower fee.  
- **Standard**: Higher volume, throughput depends on [Trust Score](https://help.twilio.com/hc/en-us/articles/1260804800549).

---

## 2. Gather information (before you start)

Use Twilio’s checklist so you’re not stuck mid-form:

- **[Gather required business information](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/collect-business-info)**  
  Covers **Customer Profile**, **Brand**, and **Campaign** fields.

Rough checklist:

**For Standard / Low-Volume Brand (business with tax ID):**

- Legal business name (exactly as on EIN/CP 575 or equivalent)
- Business type (e.g. Corporation, LLC), industry, tax ID (EIN/CBN/etc.)
- Business address, website URL, social profile URLs
- Authorized representative: name, title, email, phone (E.164)
- Brand contact email (for 2FA; not a generic or personal address)

**For Campaign (same for all paths):**

- **Use case** (e.g. `CUSTOMER_CARE`, `ACCOUNT_NOTIFICATION`, `MARKETING`, `2FA`, `LOW_VOLUME` for mixed/low volume)
- **Description** (who sends, who receives, why; 40–4096 chars)
- **Message flow** (how users opt in; 40–2049 chars)
- **Sample messages** (2–5 examples, 20–1024 chars each; include brand/website; use `[variable]` for dynamic parts)
- Whether messages contain **links** or **phone numbers**
- **Opt-in / opt-out / help** keywords and auto-reply texts (if applicable)

Accuracy and consistency (e.g. business name matching tax docs) improve your **Trust Score** and throughput.

---

## 3. Step-by-step in Twilio Console

All steps start from the same place:

**Twilio Console → Messaging → Regulatory Compliance → A2P 10DLC**  
Direct link: [A2P Onboarding](https://console.twilio.com/us1/develop/sms/regulatory-compliance/a2p-onboarding)

### Step 1: Create Primary Customer Profile (one-time)

- In the **Create Customer Profile** tab, enter the required business (or sole proprietor) details.
- This validates your identity with Twilio. If you already have a Primary Profile (e.g. for SHAKEN/STIR or CNAM), you can skip this.
- **Approval:** Often 72+ hours. You can continue to Step 2 while it’s pending.

### Step 2: Register a Brand

- In the **Register Brand** tab, create a **US A2P Brand** (Standard, Low-Volume Standard, or Sole Proprietor, depending on your path).
- Enter all required fields; for Standard/Low-Volume, include **Brand contact email** for 2FA.
- Twilio submits the Brand to **The Campaign Registry (TCR)**. Statuses:
  - **APPROVED** → You can register Campaigns.
  - **IN_REVIEW** → Manual review (e.g. 7+ business days).
  - **FAILED** / **SUSPENDED** → See [Troubleshooting A2P Brands](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/troubleshooting-a2p-brands/troubleshooting-and-rectifying-a2p-standardlvs-brands).

### Step 3: Register a Campaign and attach a Messaging Service

- **Messaging Service + number:** Create (or select) a [Messaging Service](https://www.twilio.com/docs/messaging/services) and add at least one **10DLC (Local)** number to its Sender Pool. You can buy a number during this flow or use an existing one.
- In the **Campaign Registration** tab, select the **use case** and fill in:
  - Description, message flow, message samples
  - Opt-in/opt-out/help keywords and messages (if applicable)
  - Links/phone number usage
- Associate the Campaign with that Messaging Service.
- Submit the Campaign.

**Campaign approval:** Manual vetting usually takes **about 10–15 business days**. Twilio will contact you if they need more information. After approval, that Messaging Service’s 10DLC numbers can send A2P SMS. Some use cases require extra carrier review; see [Special Use Cases](https://help.twilio.com/hc/en-us/articles/4402972441243).

---

## 4. After approval

- Use the **Messaging Service SID** (and the 10DLC numbers in its Sender Pool) in your app to send SMS (e.g. via [Twilio REST API](https://www.twilio.com/docs/sms/send-messages)).
- Keep opt-in/opt-out behavior and message content aligned with what you registered to avoid filtering or compliance issues.

---

## 5. References

- [A2P 10DLC overview](https://www.twilio.com/docs/sms/a2p-10dlc)
- [Gather business information](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/collect-business-info)
- [Direct Standard / Low-Volume onboarding](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/direct-standard-onboarding)
- [Sole Proprietor onboarding](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/direct-sole-proprietor-registration-overview)
- [Campaign use case types](https://help.twilio.com/hc/en-us/articles/1260801844470)
- [A2P 10DLC pricing and fees](https://help.twilio.com/hc/en-us/articles/1260803965530)
