function getViewedRecipesMap() {
  try {
    const raw = localStorage.getItem("viewedRecipes");
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    console.error("Не удалось прочитать viewedRecipes из localStorage", e);
    return {};
  }
}

function saveViewedRecipesMap(map) {
  try {
    localStorage.setItem("viewedRecipes", JSON.stringify(map));
  } catch (e) {
    console.error("Не удалось сохранить viewedRecipes в localStorage", e);
  }
}

function getExcludeRecipeIds() {
  const viewed = getViewedRecipesMap();
  return Object.entries(viewed)
    .filter(([key, value]) => {
      if (!value || typeof value !== "object") return false;
      const times =
        typeof value.times === "number" && !Number.isNaN(value.times)
          ? value.times
          : 0;
      return times >= 2;
    })
    .map(([key]) => Number(key))
    .filter((n) => !Number.isNaN(n));
}

function addToViewed(recipes) {
  if (!recipes || !recipes.length) return;
  const viewed = getViewedRecipesMap();
  recipes.forEach((r) => {
    if (r.id == null) return;
    const key = String(r.id);
    const prev = viewed[key];
    const prevObj = prev && typeof prev === "object" ? prev : {};
    const prevTimes =
      typeof prevObj.times === "number" && !Number.isNaN(prevObj.times)
        ? prevObj.times
        : 0;
    viewed[key] = {
      ...prevObj,
      title: r.title || prevObj.title || "Рецепт #" + r.id,
      category_lvl1: r.category_lvl1 || prevObj.category_lvl1 || "",
      times: prevTimes + 1,
    };
  });
  saveViewedRecipesMap(viewed);
}

// --- Лайки / дизлайки (для сбора данных под обучение модели) ---
const FEEDBACK_KEY = "recipeFeedback";

function getRecipeFeedbackMap() {
  try {
    const raw = localStorage.getItem(FEEDBACK_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    return {};
  }
}

function saveRecipeFeedbackMap(map) {
  try {
    localStorage.setItem(FEEDBACK_KEY, JSON.stringify(map));
  } catch (e) {
    console.error("Не удалось сохранить feedback", e);
  }
}

function setRecipeFeedback(recipeId, value) {
  const map = getRecipeFeedbackMap();
  map[String(recipeId)] = { value, at: Date.now() };
  saveRecipeFeedbackMap(map);
}

// --- Избранное ---
const FAVORITES_KEY = "favoriteRecipes";

function getFavoriteRecipesMap() {
  try {
    const raw = localStorage.getItem(FAVORITES_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    return {};
  }
}

function saveFavoriteRecipesMap(map) {
  try {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(map));
  } catch (e) {
    console.error("Не удалось сохранить избранное", e);
  }
}

function addToFavorites(recipe) {
  if (recipe.id == null) return;
  const fav = getFavoriteRecipesMap();
  const link =
    recipe.url || recipe.source_url || recipe.link || recipe.recipe_url;
  fav[String(recipe.id)] = {
    title: recipe.title || "Рецепт #" + recipe.id,
    category_lvl1: recipe.category_lvl1 || "",
    url: link || "",
  };
  saveFavoriteRecipesMap(fav);
}

function isInFavorites(recipeId) {
  return Object.prototype.hasOwnProperty.call(
    getFavoriteRecipesMap(),
    String(recipeId)
  );
}

function renderCaloriesSummary(targetCal, totalCal, deviation) {
  const el = document.getElementById("calories-summary");
  if (!el) return;
  if (totalCal == null || targetCal == null) {
    el.innerHTML = "";
    el.setAttribute("aria-hidden", "true");
    el.classList.remove("calories-summary--visible");
    return;
  }
  const sign = deviation >= 0 ? "+" : "";
  const deviationClass =
    deviation != null && Math.abs(deviation) <= 10
      ? "calories-summary__deviation--ok"
      : "";
  el.innerHTML = `
    <div class="calories-summary__grid">
      <div class="calories-summary__item">
        <span class="calories-summary__label">Цель</span>
        <span class="calories-summary__value">${targetCal} ккал</span>
      </div>
      <div class="calories-summary__item">
        <span class="calories-summary__label">Итого</span>
        <span class="calories-summary__value">${totalCal} ккал</span>
      </div>
      <div class="calories-summary__item">
        <span class="calories-summary__label">Отклонение</span>
        <span class="calories-summary__value calories-summary__deviation ${deviationClass}">${sign}${deviation}%</span>
      </div>
    </div>
  `;
  el.setAttribute("aria-hidden", "false");
  el.classList.add("calories-summary--visible");
}

function renderResults(recipes) {
  const container = document.getElementById("results");
  container.innerHTML = "";

  if (!recipes || recipes.length === 0) {
    const p = document.createElement("p");
    p.className = "placeholder";
    p.textContent =
      "Сейчас нет новых рецептов по вашей анкете. Попробуйте изменить параметры или удалить часть «просмотренных».";
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
    timeBadge.textContent = `Всего: ${ready ?? "?"} мин · Активно: ${
      kitchen ?? "?"
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

    const actions = document.createElement("div");
    actions.className = "recipe-actions";
    actions.style.display = "flex";
    actions.style.flexWrap = "wrap";
    actions.style.gap = "6px";
    actions.style.alignItems = "center";

    const link =
      recipe.url || recipe.source_url || recipe.link || recipe.recipe_url;
    if (link) {
      const anchor = document.createElement("a");
      anchor.href = link;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.textContent = "Открыть рецепт";
      anchor.className = "badge";
      actions.appendChild(anchor);
    }

    if (recipe.id !== undefined && recipe.id !== null) {
      const feedback = getRecipeFeedbackMap()[String(recipe.id)];
      const feedbackRow = document.createElement("div");
      feedbackRow.className = "feedback-row";
      const likeBtn = document.createElement("button");
      likeBtn.type = "button";
      likeBtn.className = "feedback-btn feedback-btn--like" + (feedback?.value === "like" ? " feedback-btn--active" : "");
      likeBtn.title = "Нравится";
      likeBtn.setAttribute("aria-label", "Нравится");
      likeBtn.innerHTML = '<span class="feedback-btn__icon" aria-hidden="true">👍</span>';
      likeBtn.addEventListener("click", () => {
        setRecipeFeedback(recipe.id, "like");
        likeBtn.classList.add("feedback-btn--active");
        dislikeBtn.classList.remove("feedback-btn--active");
      });
      const dislikeBtn = document.createElement("button");
      dislikeBtn.type = "button";
      dislikeBtn.className = "feedback-btn feedback-btn--dislike" + (feedback?.value === "dislike" ? " feedback-btn--active" : "");
      dislikeBtn.title = "Не нравится";
      dislikeBtn.setAttribute("aria-label", "Не нравится");
      dislikeBtn.innerHTML = '<span class="feedback-btn__icon" aria-hidden="true">👎</span>';
      dislikeBtn.addEventListener("click", () => {
        setRecipeFeedback(recipe.id, "dislike");
        dislikeBtn.classList.add("feedback-btn--active");
        likeBtn.classList.remove("feedback-btn--active");
      });
      feedbackRow.appendChild(likeBtn);
      feedbackRow.appendChild(dislikeBtn);
      actions.appendChild(feedbackRow);

      const favBtn = document.createElement("button");
      favBtn.type = "button";
      const inFav = isInFavorites(recipe.id);
      favBtn.className = "btn-favorite" + (inFav ? " btn-favorite--active" : "");
      favBtn.textContent = inFav ? "★ В избранном" : "☆ В избранное";
      favBtn.title = "Добавить в избранное";
      favBtn.addEventListener("click", () => {
        addToFavorites(recipe);
        favBtn.classList.add("btn-favorite--active");
        favBtn.textContent = "★ В избранном";
      });
      actions.appendChild(favBtn);

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.textContent = "Удалить из просмотренного";
      removeBtn.className = "badge badge--accent";
      removeBtn.style.cursor = "pointer";

      removeBtn.addEventListener("click", () => {
        const viewed = getViewedRecipesMap();
        const key = String(recipe.id);
        delete viewed[key];
        saveViewedRecipesMap(viewed);
        removeBtn.textContent = "Можно показывать снова";
        removeBtn.disabled = true;
      });

      actions.appendChild(removeBtn);
    }

    footer.appendChild(category);
    footer.appendChild(actions);

    card.appendChild(title);
    card.appendChild(meta);
    card.appendChild(footer);

    container.appendChild(card);
  });
}

async function loadPlan() {
  const statusEl = document.getElementById("status");
  const resultsContainer = document.getElementById("results");

  let payload;
  try {
    const raw = localStorage.getItem("lastQuestionnaire");
    if (!raw) {
      statusEl.textContent = "";
      renderCaloriesSummary(null, null, null);
      resultsContainer.innerHTML =
        '<p class="placeholder">Сначала заполните <a href="/" class="nav-link">анкету</a>.</p>';
      return;
    }
    payload = JSON.parse(raw);
  } catch (e) {
    console.error("Ошибка чтения анкеты из localStorage", e);
    statusEl.textContent =
      "Не удалось прочитать данные анкеты. Заполните её ещё раз.";
    renderCaloriesSummary(null, null, null);
    resultsContainer.innerHTML =
      '<p class="placeholder">Сначала заполните <a href="/" class="nav-link">анкету</a>.</p>';
    return;
  }

  statusEl.textContent = "Считаем рацион...";
  statusEl.classList.remove("status--error");

  payload.exclude_recipe_ids = getExcludeRecipeIds();

  try {
    const response = await fetch("/plan-day-from-form/", {
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
    const recipes = Array.isArray(data) ? data : (data.recipes || []);
    const targetCal = Array.isArray(data) ? null : data.target_calories;
    const totalCal = Array.isArray(data) ? null : data.total_calories;
    const deviation = Array.isArray(data) ? null : data.deviation_percent;

    addToViewed(recipes);
    renderCaloriesSummary(targetCal, totalCal, deviation);
    renderResults(recipes);
    statusEl.textContent =
      recipes.length > 0
        ? `Подобрано рецептов: ${recipes.length}`
        : "Нет новых рецептов. Удалите часть из просмотренных или ослабьте фильтры.";
  } catch (error) {
    console.error(error);
    renderCaloriesSummary(null, null, null);
    statusEl.textContent =
      "Не удалось получить рекомендации. Проверьте, что сервер запущен, и попробуйте ещё раз.";
    statusEl.classList.add("status--error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadPlan();
  const regenBtn = document.getElementById("regenerate-btn");
  if (regenBtn) {
    regenBtn.addEventListener("click", () => {
      loadPlan();
    });
  }
});

