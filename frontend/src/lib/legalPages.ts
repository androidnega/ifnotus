export type LegalSlug = 'privacy' | 'terms' | 'refunds' | 'aup' | 'nameservers' | 'pay'

export const legalPages: Record<
  LegalSlug,
  { title: string; updated: string; body: string[] }
> = {
  privacy: {
    title: 'Privacy',
    updated: '19 August 2026',
    body: [
      'IFNOTUS (Accra, Ghana) collects the name, email, phone number, and invoice details you give us so we can provide hosting and confirm Mobile Money payments.',
      'We do not sell your data. Staff see your account to confirm payments, set up hosting, and answer support tickets.',
      'Site files stay in your hosting space. We keep logs needed to run the service and to investigate abuse.',
      'Questions: support@ifnotus.space',
    ],
  },
  terms: {
    title: 'Terms of service',
    updated: '19 August 2026',
    body: [
      'Hosting is sold in Ghana Cedis. Checkout creates an invoice. Hosting starts after IFNOTUS confirms your Mobile Money payment.',
      'You must not use the service for illegal content, spam, or attacks on other systems. We may suspend a site that harms the platform or other customers.',
      'Shared hosting is not a dedicated server. CPU, RAM, and disk are limited by your pack. We keep spare capacity on the machine for the platform itself.',
      'Student addresses (surname.ifnotus.space) are included project hostnames. They are not a registered domain you can transfer away. Legacy student sites on *.serverlabsttu.space keep working.',
      'Domain registration is only completed when we have an active registrar connection. Otherwise use a name you already own, or Student.',
    ],
  },
  refunds: {
    title: 'Refunds',
    updated: '19 August 2026',
    body: [
      'Mobile Money payments are confirmed by staff against the invoice amount.',
      'If we cannot provide the hosting you paid for, we will refund or credit the unused period after you write to support.',
      'Domain registration fees already paid to a registrar are not always refundable.',
      'Ask for a refund through Support in your account, and include the invoice number and MoMo transaction ID.',
    ],
  },
  aup: {
    title: 'Acceptable use',
    updated: '19 August 2026',
    body: [
      'Do not send unsolicited bulk email, host malware, mine cryptocurrency, or attack other networks.',
      'Do not store or share illegal material. We will suspend the site and keep records required by law.',
      'One customer must not attempt to read another customer’s files or mail.',
    ],
  },
  nameservers: {
    title: 'Nameservers',
    updated: '19 August 2026',
    body: [
      'Connect custom domains either way: delegate nameservers to ns1.ifnotus.space and ns2.ifnotus.space, or keep your registrar DNS and add A records for @ and www pointing to the server IP shown in your panel.',
      'Those two nameservers are two official names for IFNOTUS DNS. They currently run on the same hosting node. Many registrars still require two names; that is expected.',
      'Your hosting panel is always https://yourdomain/cpanel (not cpanel.yourdomain). Webmail is https://yourdomain/mail. Only IFNOTUS staff uses cpanel.ifnotus.space.',
      'Student sites on *.ifnotus.space (and legacy *.serverlabsttu.space student hosts) already use IFNOTUS DNS. No nameserver change is needed.',
      'After DNS updates, turn on HTTPS in your panel.',
    ],
  },
  pay: {
    title: 'How to pay',
    updated: '25 August 2026',
    body: [
      'Choose a plan, then a domain option (register, your own domain, or Student).',
      'Open the invoice. Send the exact amount by Mobile Money to the IFNOTUS merchant number shown — MTN MoMo, Telecel Cash, or AirtelTigo Money all work.',
      'Use the invoice number as the reference. Copy the transaction ID from the SMS and paste it on the invoice.',
      'We confirm the payment (amount and ID) during support hours, then your site goes live. You will get SMS or email when it is ready.',
      'Flexible terms: pay only the invoice due for that order. Renewals and upgrades create a new invoice when you need them — no surprise auto-debits unless you turn auto-renew on.',
    ],
  },
}
