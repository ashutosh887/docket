export function canonical(value, asciiOnly = false) {
  const text = encode(value);
  return asciiOnly ? text.replace(/[\u007f-￿]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0")) : text;
}

function encode(value) {
  if (Array.isArray(value)) return "[" + value.map(encode).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map((k) => JSON.stringify(k) + ":" + encode(value[k])).join(",") + "}";
  }
  return JSON.stringify(value);
}
