const BRIDGE_VERSION = "1.3.0";
const USER_ID = "me";
const MAX_MESSAGES = 50;
const MAX_BODY_LENGTH = 500000;

function doGet() {
  return jsonOutput_({
    service: "Gmail AI Agent Bridge",
    version: BRIDGE_VERSION,
    status: "online",
    instructions: "Use an authenticated POST request."
  });
}

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonOutput_({ ok: false, error: "Missing request body" });
    }
    if (e.postData.contents.length > 1000000) {
      return jsonOutput_({ ok: false, error: "Request too large" });
    }
    const request = JSON.parse(e.postData.contents);
    const savedSecret = PropertiesService.getScriptProperties().getProperty("BRIDGE_SECRET");
    if (!constantTimeEqual_(request.secret, savedSecret)) {
      return jsonOutput_({ ok: false, error: "Unauthorized" });
    }
    const params = request.params || {};
    const result = dispatchAction_(String(request.action || ""), params);
    return jsonOutput_({ ok: true, result: result });
  } catch (err) {
    return jsonOutput_({
      ok: false,
      error: String(err && err.message ? err.message : err).slice(0, 500)
    });
  }
}

function jsonOutput_(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}

function constantTimeEqual_(a, b) {
  if (typeof a !== "string" || typeof b !== "string" ||
      a.length < 32 || a.length !== b.length) return false;
  let difference = 0;
  for (let i = 0; i < a.length; i++) {
    difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return difference === 0;
}

function authorizeBridge() {
  const profile = Gmail.Users.getProfile(USER_ID);
  Calendar.Events.list("primary", {
    maxResults: 1,
    singleEvents: true,
    orderBy: "startTime"
  });
  const result = {
    authorized: true,
    account: profile.emailAddress,
    gmailApi: "available",
    calendarApi: "available",
    version: BRIDGE_VERSION
  };
  console.log(JSON.stringify(result));
  return result;
}

function dispatchAction_(action, p) {
  switch (action) {
    case "health":
    case "profile": return getProfile_();
    case "list_emails": return listEmails_(p);
    case "get_email": return getEmail_(requiredString_(p.message_id, "message_id"));
    case "get_thread": return getThread_(requiredString_(p.thread_id, "thread_id"));
    case "list_labels": return listLabels_();
    case "create_label": return createLabel_(p.name);
    case "modify_labels": return modifyLabels_(p.message_id, p.add_labels || [], p.remove_labels || []);
    case "archive": return threadAction_(p.message_id, "archive", p);
    case "trash": return threadAction_(p.message_id, "trash", p);
    case "mark_read": return threadAction_(p.message_id, "read", p);
    case "mark_unread": return threadAction_(p.message_id, "unread", p);
    case "batch_modify": return batchModify_(p);
    case "create_draft": return createDraft_(p);
    case "send_draft":
      requireConfirmation_(p, "Sending a draft");
      return sendDraft_(p.draft_id);
    case "delete_draft":
      requireConfirmation_(p, "Deleting a draft");
      return deleteDraft_(p.draft_id);
    case "send_message":
      requireConfirmation_(p, "Sending an email");
      return sendMessage_(p);
    case "get_attachment": return getAttachment_(p.message_id, p.attachment_id);
    case "list_calendar_events": return listCalendarEvents_(p);
    case "create_calendar_event":
      requireConfirmation_(p, "Creating a calendar event");
      return createCalendarEvent_(p);
    default: throw new Error("Unsupported action: " + action);
  }
}

function requiredString_(value, name) {
  if (typeof value !== "string" || !value.trim()) throw new Error("Missing required field: " + name);
  return value.trim();
}

function requireConfirmation_(p, operation) {
  if (p.confirmed !== true) {
    throw new Error(operation + " requires params.confirmed=true after explicit user approval.");
  }
}

function withGmailRetry_(operation, callback) {
  const maxAttempts = 4;
  let lastError;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return callback();
    } catch (err) {
      lastError = err;
      const message = String(err && err.message ? err.message : err);
      const retryable = /quota|rate.?limit|userRateLimitExceeded|rateLimitExceeded|too many requests|HTTP.?429|backendError|temporar/i.test(message);
      if (!retryable || attempt === maxAttempts - 1) {
        throw new Error(operation + " failed: " + message.slice(0, 400));
      }
      Utilities.sleep((1000 * Math.pow(2, attempt)) + Math.floor(Math.random() * 300));
    }
  }
  throw lastError;
}

function getProfile_() {
  const profile = withGmailRetry_("get profile", function () {
    return Gmail.Users.getProfile(USER_ID);
  });
  return {
    email: profile.emailAddress || "",
    connected: Boolean(profile.emailAddress),
    messages_total: profile.messagesTotal || 0,
    threads_total: profile.threadsTotal || 0,
    history_id: profile.historyId || "",
    bridge_version: BRIDGE_VERSION
  };
}

function listEmails_(p) {
  const pageSize = Math.max(1, Math.min(10, Number(p.max_results) || 10));
  const options = {
    q: String(p.query || "in:anywhere").slice(0, 500),
    maxResults: pageSize
  };
  if (p.page_token && String(p.page_token) !== "0") options.pageToken = String(p.page_token);
  const response = withGmailRetry_("list messages", function () {
    return Gmail.Users.Messages.list(USER_ID, options);
  });
  const messages = response.messages || [];
  const labelMap = getLabelMap_();
  const items = [];
  for (let i = 0; i < messages.length; i++) {
    const full = withGmailRetry_("fetch message", function () {
      return Gmail.Users.Messages.get(USER_ID, messages[i].id, { format: "full" });
    });
    items.push(serializeMessage_(full, labelMap, false));
    if (i < messages.length - 1) Utilities.sleep(250);
  }
  return {
    items: items,
    total_estimate: response.resultSizeEstimate || items.length,
    next_page_token: response.nextPageToken || null
  };
}

function getEmail_(messageId) {
  const message = withGmailRetry_("fetch message", function () {
    return Gmail.Users.Messages.get(USER_ID, messageId, { format: "full" });
  });
  return serializeMessage_(message, getLabelMap_());
}

function getThread_(threadId) {
  const thread = withGmailRetry_("fetch thread", function () {
    return Gmail.Users.Threads.get(USER_ID, threadId, { format: "full" });
  });
  const labelMap = getLabelMap_();
  return (thread.messages || []).map(function (message) {
    return serializeMessage_(message, labelMap);
  });
}

function getHeaderMap_(message) {
  const result = {};
  const headers = message.payload && message.payload.headers ? message.payload.headers : [];
  headers.forEach(function (header) {
    result[String(header.name).toLowerCase()] = header.value || "";
  });
  return result;
}

function decodeBodyData_(data) {
  if (!data) return "";
  try {
    const bytes = Utilities.base64DecodeWebSafe(data);
    return Utilities.newBlob(bytes).getDataAsString("UTF-8");
  } catch (_) {
    return "";
  }
}

function walkMimeParts_(part, output, includeBody) {
  if (!part) return;
  if (part.filename && part.body && part.body.attachmentId) {
    output.attachments.push({
      attachment_id: part.body.attachmentId,
      part_id: part.partId || "",
      filename: part.filename,
      mime_type: part.mimeType || "application/octet-stream",
      size: Number(part.body.size || 0)
    });
  }
  const data = part.body && part.body.data;
  if (data && includeBody !== false) {
    const mimeType = String(part.mimeType || "").toLowerCase();
    const text = decodeBodyData_(data);
    if (mimeType === "text/plain" && output.text === null) output.text = text;
    else if (mimeType === "text/html" && output.html === null) output.html = text;
  }
  (part.parts || []).forEach(function (child) {
    walkMimeParts_(child, output, includeBody);
  });
}

/**
 * Decode numeric and common named HTML entities without interpreting the body
 * as executable HTML. This preserves apostrophes and punctuation in previews.
 */
function decodeHtmlEntities_(value) {
  const named = {
    amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ",
    rsquo: "'", lsquo: "'", rdquo: '"', ldquo: '"',
    ndash: "–", mdash: "—", hellip: "…", copy: "©", reg: "®",
    trade: "™", bull: "•", middot: "·"
  };
  let text = String(value || "");
  text = text.replace(/&#(x[0-9a-f]+|[0-9]+);?/gi, function (whole, code) {
    const hex = String(code).charAt(0).toLowerCase() === "x";
    const point = parseInt(hex ? String(code).slice(1) : code, hex ? 16 : 10);
    try {
      return point > 0 && point <= 0x10ffff ? String.fromCodePoint(point) : whole;
    } catch (_) {
      return whole;
    }
  });
  return text.replace(/&([a-z]+);/gi, function (whole, name) {
    return Object.prototype.hasOwnProperty.call(named, String(name).toLowerCase())
      ? named[String(name).toLowerCase()] : whole;
  });
}

/**
 * Convert HTML-only messages into readable text. We deliberately return text,
 * not raw HTML, so the frontend can render it in a text node without XSS risk.
 */
function htmlToPlainText_(html) {
  let text = String(html || "");
  text = text
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<(script|style|head|title|svg)[^>]*>[\s\S]*?<\/\1\s*>/gi, " ")
    .replace(/<\s*br\s*\/?\s*>/gi, "\n")
    .replace(/<\s*li\b[^>]*>/gi, "• ")
    .replace(/<\/\s*(p|div|li|tr|table|h[1-6]|blockquote|pre|section|article)\s*>/gi, "\n")
    .replace(/<[^>]*>/g, " ")
    .replace(/\r/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\n{3,}/g, "\n\n");
  return decodeHtmlEntities_(text).trim();
}

function serializeMessage_(message, labelMap, includeBody) {
  const headers = getHeaderMap_(message);
  const payload = message.payload || {};
  const parsed = { text: null, html: null, attachments: [] };
  walkMimeParts_(payload, parsed, includeBody !== false);
  const labels = (message.labelIds || []).map(function (id) {
    return labelMap[id] || id;
  });

  const sourceBody = includeBody === false ? "" : (parsed.text !== null
    ? String(parsed.text)
    : parsed.html !== null ? htmlToPlainText_(parsed.html) : "");
  const truncated = sourceBody.length > MAX_BODY_LENGTH;
  const body = sourceBody.slice(0, MAX_BODY_LENGTH);
  let internalDate = "";
  if (message.internalDate) internalDate = new Date(Number(message.internalDate)).toISOString();

  return {
    id: message.id || "",
    thread_id: message.threadId || "",
    from_address: headers.from || "",
    to_addresses: headers.to || "",
    cc_addresses: headers.cc || "",
    reply_to: headers["reply-to"] || headers.from || "",
    subject: headers.subject || "(no subject)",
    snippet: decodeHtmlEntities_(message.snippet || body.slice(0, 200)),
    body_text: body,
    body_format: "plain",
    body_truncated: truncated,
    internal_date: internalDate,
    labels: labels,
    is_unread: labels.indexOf("UNREAD") !== -1,
    is_sent: labels.indexOf("SENT") !== -1,
    has_attachments: parsed.attachments.length > 0,
    attachment_metadata: parsed.attachments,
    raw_headers: {
      "message-id": headers["message-id"] || "",
      "in-reply-to": headers["in-reply-to"] || "",
      "references": headers.references || "",
      "reply-to": headers["reply-to"] || "",
      "list-unsubscribe": headers["list-unsubscribe"] || ""
    }
  };
}

function getLabelMap_() {
  const cache = CacheService.getScriptCache();
  const cacheKey = "gmail_label_map_v1";
  const cached = cache.get(cacheKey);
  if (cached) {
    try { return JSON.parse(cached); }
    catch (_) { cache.remove(cacheKey); }
  }
  const result = withGmailRetry_("list labels", function () {
    return Gmail.Users.Labels.list(USER_ID);
  });
  const map = {};
  (result.labels || []).forEach(function (label) { map[label.id] = label.name; });
  try { cache.put(cacheKey, JSON.stringify(map), 300); } catch (_) {}
  return map;
}

function listLabels_() {
  const result = Gmail.Users.Labels.list(USER_ID);
  return (result.labels || []).map(function (label) {
    return { id: label.id, name: label.name, type: label.type || "user" };
  });
}

function createLabel_(name) {
  const cleanName = requiredString_(name, "name");
  if (cleanName.length > 225 || /[\r\n]/.test(cleanName)) throw new Error("Invalid label name");
  const existing = Gmail.Users.Labels.list(USER_ID).labels || [];
  const match = existing.filter(function (label) { return label.name === cleanName; })[0];
  if (match) return { id: match.id, name: match.name };
  const created = Gmail.Users.Labels.create({
    name: cleanName, labelListVisibility: "labelShow", messageListVisibility: "show"
  }, USER_ID);
  return { id: created.id, name: created.name };
}

function resolveLabelIds_(names, createMissing) {
  const systemLabels = ["INBOX", "UNREAD", "STARRED", "IMPORTANT", "SENT", "TRASH", "SPAM", "DRAFT"];
  const existing = Gmail.Users.Labels.list(USER_ID).labels || [];
  const ids = [];
  (Array.isArray(names) ? names : []).forEach(function (raw) {
    const name = requiredString_(String(raw), "label");
    const upper = name.toUpperCase();
    if (systemLabels.indexOf(upper) !== -1) { ids.push(upper); return; }
    let match = existing.filter(function (label) { return label.name === name || label.id === name; })[0];
    if (!match && createMissing) {
      match = Gmail.Users.Labels.create({
        name: name, labelListVisibility: "labelShow", messageListVisibility: "show"
      }, USER_ID);
      existing.push(match);
    }
    if (match) ids.push(match.id);
  });
  return ids.filter(function (id, index, all) { return all.indexOf(id) === index; });
}

function getMessageThreadId_(messageId) {
  const message = Gmail.Users.Messages.get(USER_ID, requiredString_(messageId, "message_id"), { format: "minimal" });
  if (!message.threadId) throw new Error("Message thread not found");
  return message.threadId;
}

function modifyThreadLabels_(threadId, addNames, removeNames) {
  const addIds = resolveLabelIds_(addNames, true);
  const removeIds = resolveLabelIds_(removeNames, false);
  Gmail.Users.Threads.modify({ addLabelIds: addIds, removeLabelIds: removeIds }, USER_ID, threadId);
  return { success: true, thread_id: threadId, add_labels: addNames, remove_labels: removeNames };
}

function modifyLabels_(messageId, addLabels, removeLabels) {
  const threadId = getMessageThreadId_(messageId);
  return modifyThreadLabels_(threadId,
    Array.isArray(addLabels) ? addLabels : [],
    Array.isArray(removeLabels) ? removeLabels : []);
}

function threadAction_(messageId, action, p) {
  const threadId = getMessageThreadId_(messageId);
  if (action === "trash") {
    requireConfirmation_(p, "Moving a thread to Trash");
    return modifyThreadLabels_(threadId, ["TRASH"], []);
  }
  if (action === "archive") return modifyThreadLabels_(threadId, [], ["INBOX"]);
  if (action === "read") return modifyThreadLabels_(threadId, [], ["UNREAD"]);
  if (action === "unread") return modifyThreadLabels_(threadId, ["UNREAD"], []);
  throw new Error("Unsupported thread action");
}

function batchModify_(p) {
  const ids = Array.isArray(p.message_ids) ? p.message_ids : [];
  const add = Array.isArray(p.add_labels) ? p.add_labels : [];
  const remove = Array.isArray(p.remove_labels) ? p.remove_labels : [];
  if (ids.length > MAX_MESSAGES) throw new Error("Maximum " + MAX_MESSAGES + " messages per batch");
  const addsUpper = add.map(function (x) { return String(x).toUpperCase(); });
  if (addsUpper.indexOf("TRASH") !== -1 || addsUpper.indexOf("SPAM") !== -1) {
    requireConfirmation_(p, "Bulk moving emails to Trash or Spam");
  }
  return { count: ids.length, results: ids.map(function (id) { return modifyLabels_(id, add, remove); }) };
}

function sanitizeHeader_(value) {
  return String(value || "").replace(/[\r\n]+/g, " ").trim();
}

function recipientString_(value) {
  if (Array.isArray(value)) return value.map(sanitizeHeader_).filter(Boolean).join(", ");
  return sanitizeHeader_(value);
}

function encodeSubject_(subject) {
  if (/^[\x20-\x7E]*$/.test(subject)) return subject;
  const bytes = Utilities.newBlob(subject, "text/plain").getBytes();
  return "=?UTF-8?B?" + Utilities.base64Encode(bytes) + "?=";
}

function buildRawMessage_(to, cc, bcc, subject, body, replyHeaders) {
  const lines = [];
  if (to) lines.push("To: " + to);
  if (cc) lines.push("Cc: " + cc);
  if (bcc) lines.push("Bcc: " + bcc);
  lines.push("Subject: " + encodeSubject_(sanitizeHeader_(subject)));
  if (replyHeaders && replyHeaders.inReplyTo) lines.push("In-Reply-To: " + sanitizeHeader_(replyHeaders.inReplyTo));
  if (replyHeaders && replyHeaders.references) lines.push("References: " + sanitizeHeader_(replyHeaders.references));
  lines.push("MIME-Version: 1.0");
  lines.push("Content-Type: text/plain; charset=UTF-8");
  lines.push("Content-Transfer-Encoding: base64");
  lines.push("");
  const bodyBytes = Utilities.newBlob(String(body || ""), "text/plain").getBytes();
  const encodedBody = Utilities.base64Encode(bodyBytes);
  lines.push((encodedBody.match(/.{1,76}/g) || [""]).join("\r\n"));
  const raw = Utilities.base64EncodeWebSafe(
    Utilities.newBlob(lines.join("\r\n"), "message/rfc822").getBytes()
  ).replace(/=+$/, "");
  return raw;
}

function createDraft_(p) {
  let to = recipientString_(p.to_addresses);
  let subject = sanitizeHeader_(p.subject);
  const cc = recipientString_(p.cc_addresses);
  const bcc = recipientString_(p.bcc_addresses);
  const body = String(p.body_text || "");
  if (!body.trim()) throw new Error("Draft body cannot be empty");
  let threadId = "";
  let replyHeaders = null;
  if (p.thread_id) {
    const thread = Gmail.Users.Threads.get(USER_ID, requiredString_(p.thread_id, "thread_id"), { format: "full" });
    const messages = thread.messages || [];
    if (!messages.length) throw new Error("The requested thread is empty");
    const last = messages[messages.length - 1];
    const lastHeaders = getHeaderMap_(last);
    if (!to) to = sanitizeHeader_(lastHeaders["reply-to"] || lastHeaders.from);
    if (!subject) {
      const oldSubject = lastHeaders.subject || "";
      subject = /^re:/i.test(oldSubject) ? oldSubject : "Re: " + oldSubject;
    }
    const previousReferences = lastHeaders.references || "";
    const messageIdHeader = lastHeaders["message-id"] || "";
    replyHeaders = {
      inReplyTo: messageIdHeader,
      references: (previousReferences + " " + messageIdHeader).trim()
    };
    threadId = thread.id;
  }
  if (!to) throw new Error("At least one recipient is required");
  const raw = buildRawMessage_(to, cc, bcc, subject, body, replyHeaders);
  const messageResource = { raw: raw };
  if (threadId) messageResource.threadId = threadId;
  const draft = Gmail.Users.Drafts.create({ message: messageResource }, USER_ID);
  return {
    id: draft.id,
    message_id: draft.message ? draft.message.id : "",
    thread_id: draft.message ? draft.message.threadId : threadId,
    created: true
  };
}

function sendDraft_(draftId) {
  const sent = Gmail.Users.Drafts.send({ id: requiredString_(draftId, "draft_id") }, USER_ID);
  return { id: sent.id || "", threadId: sent.threadId || "", sent: true };
}

function deleteDraft_(draftId) {
  Gmail.Users.Drafts.remove(USER_ID, requiredString_(draftId, "draft_id"));
  return { deleted: true };
}

function sendMessage_(p) {
  const to = recipientString_(p.to_addresses);
  const cc = recipientString_(p.cc_addresses);
  const bcc = recipientString_(p.bcc_addresses);
  const subject = sanitizeHeader_(p.subject);
  const body = String(p.body_text || "");
  if (!to || !body.trim()) throw new Error("Recipient and message body are required");
  const raw = buildRawMessage_(to, cc, bcc, subject, body, null);
  const sent = Gmail.Users.Messages.send({ raw: raw }, USER_ID);
  return { id: sent.id || "", threadId: sent.threadId || "", sent: true };
}

function getAttachment_(messageId, attachmentId) {
  const id = requiredString_(messageId, "message_id");
  const partId = requiredString_(attachmentId, "attachment_id");
  const attachment = Gmail.Users.Messages.Attachments.get(USER_ID, id, partId);
  const bytes = Utilities.base64DecodeWebSafe(attachment.data || "");
  return {
    attachment_id: partId,
    size: attachment.size || bytes.length,
    data_base64: Utilities.base64Encode(bytes)
  };
}

function listCalendarEvents_(p) {
  const timeMin = requiredString_(p.time_min, "time_min");
  const timeMax = requiredString_(p.time_max, "time_max");
  if (isNaN(Date.parse(timeMin)) || isNaN(Date.parse(timeMax)) || Date.parse(timeMax) <= Date.parse(timeMin)) {
    throw new Error("Invalid calendar date range");
  }
  const response = Calendar.Events.list("primary", {
    timeMin: timeMin, timeMax: timeMax,
    maxResults: Math.max(1, Math.min(50, Number(p.max_results) || 20)),
    singleEvents: true, orderBy: "startTime"
  });
  return (response.items || []).map(serializeCalendarEvent_);
}

function createCalendarEvent_(p) {
  const summary = requiredString_(p.summary, "summary");
  const start = new Date(requiredString_(p.start, "start"));
  const end = new Date(requiredString_(p.end, "end"));
  if (isNaN(start.getTime()) || isNaN(end.getTime()) || end <= start) throw new Error("Invalid calendar event dates");
  const event = {
    summary: summary,
    description: String(p.description || ""),
    start: { dateTime: start.toISOString(), timeZone: "Asia/Kolkata" },
    end: { dateTime: end.toISOString(), timeZone: "Asia/Kolkata" }
  };
  if (Array.isArray(p.attendees) && p.attendees.length) {
    event.attendees = p.attendees.map(function (email) { return { email: requiredString_(email, "attendee email") }; });
  }
  const created = Calendar.Events.insert(event, "primary", { sendUpdates: "none" });
  return serializeCalendarEvent_(created);
}

function serializeCalendarEvent_(event) {
  return {
    id: event.id || "",
    summary: event.summary || "",
    description: event.description || "",
    start: event.start ? (event.start.dateTime || event.start.date || "") : "",
    end: event.end ? (event.end.dateTime || event.end.date || "") : "",
    timezone: (event.start && event.start.timeZone) || Session.getScriptTimeZone()
  };
}
