const ALLERGENS = [
  "Белок коровьего молока",
  "Злаки, содержащие глютен",
  "Яйцо",
  "Рыба",
  "Сельдерей",
  "Соя",
  "Пищевые добавки",
  "Горчица",
  "Орехи",
  "Клубника",
  "Кунжут",
  "Арахис",
  "Ракообразные",
  "Моллюски",
];

const CUISINES = [
  { key: "asian", label: "Азиатская" },
  { key: "european", label: "Европейская" },
  { key: "eastern", label: "Ближневосточная" },
  { key: "slavic", label: "Славянская" },
  { key: "america", label: "Американская" },
  { key: "mexica", label: "Мексиканская" },
];

function renderCheckboxes() {
  const allergensContainer = document.getElementById("allergens-container");
  const cuisinesContainer = document.getElementById("cuisines-container");

  ALLERGENS.forEach((name, index) => {
    const id = `allergen_${index}`;
    const label = document.createElement("label");
    label.className = "chip";
    label.htmlFor = id;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = id;
    checkbox.dataset.allergenKey = name;

    const span = document.createElement("span");
    span.textContent = name;

    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        label.classList.add("chip--active");
      } else {
        label.classList.remove("chip--active");
      }
    });

    label.appendChild(checkbox);
    label.appendChild(span);
    allergensContainer.appendChild(label);
  });

  CUISINES.forEach(({ key, label: text }) => {
    const id = `cuisine_${key}`;
    const label = document.createElement("label");
    label.className = "chip";
    label.htmlFor = id;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = id;
    checkbox.dataset.cuisineKey = key;

    const span = document.createElement("span");
    span.textContent = text;

    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        label.classList.add("chip--active");
      } else {
        label.classList.remove("chip--active");
      }
    });

    label.appendChild(checkbox);
    label.appendChild(span);
    cuisinesContainer.appendChild(label);
  });
}

function collectFormData() {
  const height = parseFloat(document.getElementById("height_cm").value);
  const weight = parseFloat(document.getElementById("weight_kg").value);
  const sexInput = document.querySelector('input[name="sex"]:checked');
  const activityInput = document.querySelector(
    'input[name="activity_level"]:checked'
  );
  const sex = sexInput ? sexInput.value : "";
  const activityLevel = activityInput ? activityInput.value : "";
  const activeCookMinutes = parseInt(
    document.getElementById("active_cook_minutes").value,
    10
  );
  const passiveCookMinutes = parseInt(
    document.getElementById("passive_cook_minutes").value,
    10
  );

  const allergens = {};
  document
    .querySelectorAll("#allergens-container input[type='checkbox']")
    .forEach((checkbox) => {
      const key = checkbox.dataset.allergenKey;
      allergens[key] = checkbox.checked ? 1 : 0;
    });

  const cuisines = {};
  document
    .querySelectorAll("#cuisines-container input[type='checkbox']")
    .forEach((checkbox) => {
      const key = checkbox.dataset.cuisineKey;
      cuisines[key] = checkbox.checked ? 1 : 0;
    });

  return {
    height_cm: height,
    weight_kg: weight,
    sex,
    activity_level: activityLevel,
    passive_cook_minutes: passiveCookMinutes,
    active_cook_minutes: activeCookMinutes,
    allergens,
    cuisines,
  };
}

function initSegments(groupName) {
  const inputs = document.querySelectorAll(`input[name="${groupName}"]`);
  inputs.forEach((input) => {
    const label = input.parentElement;
    if (input.checked) {
      label.classList.add("segment--active");
    }
    input.addEventListener("change", () => {
      inputs.forEach((i) => i.parentElement.classList.remove("segment--active"));
      if (input.checked) {
        label.classList.add("segment--active");
      }
    });
  });
}

function handleSubmit(event) {
  event.preventDefault();
  const statusEl = document.getElementById("status");
  statusEl.textContent = "Анкета сохранена. Переходим к рациону...";
  statusEl.classList.remove("status--error");

  const payload = collectFormData();
  try {
    localStorage.setItem("lastQuestionnaire", JSON.stringify(payload));
  } catch (e) {
    console.error("Не удалось сохранить анкету в localStorage", e);
  }

  window.location.href = "/plan";
}

document.addEventListener("DOMContentLoaded", () => {
  renderCheckboxes();
  const form = document.getElementById("questionnaire-form");
  form.addEventListener("submit", handleSubmit);
  initSegments("sex");
  initSegments("activity_level");
});

