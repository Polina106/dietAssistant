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
  const sex = document.getElementById("sex").value;
  const activityLevel = document.getElementById("activity_level").value;
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

function renderResults(recipes) {
  const container = document.getElementById("results");
  container.innerHTML = "";

  if (!recipes || recipes.length === 0) {
    const p = document.createElement("p");
    p.className = "placeholder";
    p.textContent =
      "По заданным параметрам ничего не найдено. Попробуйте ослабить фильтры (уменьшить список аллергенов или увеличить допустимое время готовки).";
    container.appendChild(p);
    return;
  }

  recipes.forEach((recipe) => {
    const card = document.createElement("article");
    card.className = "recipe-card";

    const title = document.createElement("div");
    title.className = "recipe-title";
    title.textContent = recipe.title || `Рецепт #${recipe.id}`;

    const meta = document.createElement("div");
    meta.className = "recipe-meta";

    const timeBadge = document.createElement("span");
    timeBadge.className = "badge";
    const ready = recipe.ready_in_minutes ?? recipe.readyInMinutes;
    const kitchen = recipe.kitchen_time_in_minutes ?? recipe.kitchenTimeInMinutes;
    timeBadge.textContent = `Всего: ${ready ?? "?"} мин · Активно: ${kitchen ?? "?"
      } мин`;

    const caloriesBadge = document.createElement("span");
    caloriesBadge.className = "badge badge--accent";
    if (typeof recipe.calories === "number") {
      caloriesBadge.textContent = `${Math.round(recipe.calories)} ккал`;
    } else {
      caloriesBadge.textContent = "Калорийность не указана";
    }

    meta.appendChild(timeBadge);
    meta.appendChild(caloriesBadge);

    const footer = document.createElement("div");
    footer.className = "recipe-footer";

    const category = document.createElement("span");
    category.className = "recipe-category";
    category.textContent = recipe.category_lvl1 || "";

    const link =
      recipe.url || recipe.source_url || recipe.link || recipe.recipe_url;
    if (link) {
      const anchor = document.createElement("a");
      anchor.href = link;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.textContent = "Открыть рецепт";
      anchor.className = "badge";
      footer.appendChild(anchor);
    }

    footer.appendChild(category);

    card.appendChild(title);
    card.appendChild(meta);
    card.appendChild(footer);

    container.appendChild(card);
  });
}

async function handleSubmit(event) {
  event.preventDefault();
  const statusEl = document.getElementById("status");
  const submitBtn = event.target.querySelector("button[type='submit']");

  statusEl.textContent = "Считаем рацион...";
  statusEl.classList.remove("status--error");
  submitBtn.disabled = true;

  try {
    const payload = collectFormData();

    const response = await fetch("/status/plan-day-from-form/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Ошибка сервера: ${response.status}`);
    }

    const data = await response.json();
    renderResults(data);
    statusEl.textContent = `Найдено рецептов: ${data.length}`;
  } catch (error) {
    console.error(error);
    statusEl.textContent =
      "Не удалось получить рекомендации. Проверьте, что сервер запущен, и попробуйте ещё раз.";
    statusEl.classList.add("status--error");
  } finally {
    submitBtn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  renderCheckboxes();
  const form = document.getElementById("questionnaire-form");
  form.addEventListener("submit", handleSubmit);
});

