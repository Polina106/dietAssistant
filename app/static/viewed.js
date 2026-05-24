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

function removeFromViewed(recipeId) {
  const viewed = getViewedRecipesMap();
  delete viewed[String(recipeId)];
  saveViewedRecipesMap(viewed);
  renderViewedList();
}

function renderViewedList() {
  const container = document.getElementById("viewed-list");
  if (!container) return;

  const viewed = getViewedRecipesMap();
  const ids = Object.keys(viewed).filter((k) => k !== "" && !Number.isNaN(Number(k)));

  container.innerHTML = "";

  if (ids.length === 0) {
    const p = document.createElement("p");
    p.className = "placeholder";
    p.textContent = "Просмотренных рецептов пока нет. Они появятся здесь после подбора рациона.";
    container.appendChild(p);
    return;
  }

  ids.forEach((id) => {
    const data = viewed[id];
    const title =
      typeof data === "object" && data && data.title
        ? data.title
        : "Рецепт #" + id;
    const category =
      typeof data === "object" && data && data.category_lvl1
        ? data.category_lvl1
        : "";

    const card = document.createElement("article");
    card.className = "recipe-card recipe-card--viewed";

    const row = document.createElement("div");
    row.className = "viewed-row";

    const info = document.createElement("div");
    info.className = "viewed-info";
    const titleEl = document.createElement("div");
    titleEl.className = "recipe-title";
    titleEl.textContent = title;
    info.appendChild(titleEl);
    if (category) {
      const catEl = document.createElement("div");
      catEl.className = "recipe-category";
      catEl.textContent = category;
      info.appendChild(catEl);
    }

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "Удалить из просмотренных";
    removeBtn.className = "primary-btn primary-btn--ghost primary-btn--sm";
    removeBtn.addEventListener("click", () => removeFromViewed(id));

    row.appendChild(info);
    row.appendChild(removeBtn);
    card.appendChild(row);
    container.appendChild(card);
  });
}

document.addEventListener("DOMContentLoaded", renderViewedList);
