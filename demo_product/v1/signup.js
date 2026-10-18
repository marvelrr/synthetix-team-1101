"use strict";
const form = document.querySelector("form");
form.addEventListener("submit", (event) => {
  event.preventDefault();
  const error = document.getElementById("form-error");
  if (!form.checkValidity()) {
    error.textContent = "Please complete your name, a valid email and a contact phone number.";
    form.reportValidity();
    return;
  }
  error.textContent = "";
  // Static demonstration only: no fetch, storage, backend or external calls.
  window.location.assign("welcome.html");
});
