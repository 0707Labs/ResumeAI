/** Fetch a same-origin signed download link: the browser saves the attachment and stays on
 * the page. The link works once the backend has checked and charged the download. */
export function openDownload(url: string) {
  const a = document.createElement("a");
  a.href = url;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
