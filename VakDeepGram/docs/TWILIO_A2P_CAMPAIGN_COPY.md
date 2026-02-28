# A2P 10DLC Campaign Copy (Sole Proprietor)

Use this text when registering your Campaign in Twilio Console. Replace placeholders like `[Your Name]` and `[your-website.com]` with your real details. Keep wording consistent with your actual opt-in method and message content.

---

## Campaign description

**Length:** 40–4096 characters. Use the following and adjust as needed.

```
This campaign sends SMS notifications to individuals who have opted in to receive messages from [Your Name]. Messages include appointment reminders, booking confirmations, and scheduling updates for services they requested via [your website / phone / voice assistant]. Recipients are people who explicitly consented to receive these texts when they booked or signed up. Message and data rates may apply. Recipients can opt out at any time by replying STOP.
```

**Shorter variant (if you need under 300 chars):**

```
[Your Name] sends appointment reminders and booking-related notifications to people who opted in (e.g. when scheduling). Messages include confirmations and reminders. Recipients can opt out by replying STOP. Msg & data rates may apply.
```

---

## Message flow / how users opt in

**Length:** 40–2049 characters. Describe exactly how someone consents.

```
End users opt in by [choose one or more that apply]:

• Visiting [https://your-website.com] and entering their mobile number and checking a box to receive SMS notifications (appointment reminders, booking confirmations). Terms of Service at [https://your-website.com/terms]. Privacy Policy at [https://your-website.com/privacy].

• [If applicable:] Telling the voice assistant or booking system they agree to receive text messages when prompted during booking.

• [If applicable:] Texting START or JOIN to [your Twilio number] after seeing the opt-in prompt on the website or during a call.

Consent is collected before any marketing or promotional messages are sent. Users are informed that message and data rates may apply and that they can opt out by replying STOP. Help is available by replying HELP.
```

**Minimal (website-only) variant:**

```
End users opt in by visiting [https://your-website.com], entering their phone number, and checking a box to receive appointment and booking SMS notifications. Terms at [url], Privacy at [url]. They can opt out anytime by replying STOP. Msg & data rates may apply.
```

---

## Sample messages (2 required, 20–1024 chars each)

Use brackets `[ ]` for variable content. Include your name or site and an opt-out line.

**Sample 1 – Appointment reminder**

```
Hi, this is [Your Name]. Reminder: your appointment is scheduled for [date] at [time]. Reply STOP to opt out of these messages. Msg & data rates may apply.
```

**Sample 2 – Booking confirmation**

```
[Your Name]: Your booking is confirmed for [date] at [time]. Reply STOP to unsubscribe. Need help? Reply HELP. Msg & data rates may apply.
```

**Sample 3 – Alternative (second reminder style)**

```
Reminder from [Your Name]: You have an upcoming appointment on [date] at [time]. Reply STOP to stop these reminders. Msg & data rates may apply.
```

Use **Sample 1** and **Sample 2** (or **Sample 3**) as your two required samples. If your messages will include a link or phone number, say so in the campaign form and include one in a sample, e.g.:

```
[Your Name]: Your appointment is confirmed. View details: [https://your-site.com/booking/123]. Reply STOP to opt out. Msg & data rates may apply.
```

---

## Opt-in keywords (if users can text to opt in)

If users can text a keyword to your number to opt in, list them here. Otherwise leave blank.

| Field | Value |
|-------|--------|
| **Opt-in keywords** | `START`, `JOIN`, `UNSTOP` |
| **Opt-in message** | `You're now subscribed to messages from [Your Name]. You'll receive appointment reminders and booking updates. Reply STOP to opt out, HELP for help. Msg & data rates may apply.` |

---

## Opt-out and help (recommended: use Twilio defaults)

Twilio can fill these for you. If you manage them yourself, use:

| Field | Value |
|-------|--------|
| **Opt-out keywords** | `STOP`, `STOPALL`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT` |
| **Opt-out message** | `You have been unsubscribed from [Your Name]. You will not receive any more messages. Reply START to resubscribe.` |
| **Help keywords** | `HELP`, `INFO`, `SUPPORT` |
| **Help message** | `[Your Name]: Appointment reminders and booking updates. Msg & data rates may apply. Reply STOP to opt out.` |

---

## Checklist before submit

- [ ] Replaced all `[Your Name]` and `[your-website.com]` (and any `[date]`, `[time]`, `[url]`) with real values.
- [ ] Campaign description matches how you actually collect consent and what you send.
- [ ] Message flow describes your real opt-in method(s); URLs work and have Terms/Privacy if you mention them.
- [ ] Sample messages include your name/site and an opt-out line; no misleading or promotional content you won’t send.
- [ ] If you use keyword opt-in, opt-in keywords and opt-in message are filled; otherwise leave opt-in keywords blank.
- [ ] Opt-out/help either use Twilio defaults or match the table above.
