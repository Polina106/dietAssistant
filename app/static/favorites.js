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

function removeFromFavorites(recipeId) {
  const fav = getFavoriteRecipesMap();
  delete fav[String(recipeId)];
  saveFavoriteRecipesMap(fav);
  renderFavoritesList();
}

function renderFavoritesList() {
  const container = document.getElementById("favorites-list");
  if (!container) return;

  const fav = getFavoriteRecipesMap();
  const ids = Object.keys(fav).filter((k) => k !== "");

  container.innerHTML = "";

  if (ids.length === 0) {
    const p = document.createElement("p");
    p.className = "placeholder";
    p.textContent = "В избранном пока ничего нет. Добавляйте рецепты с страницы рациона (кнопка «В избранное»).";
    container.appendChild(p);
    return;
  }

  ids.forEach((id) => {
    const data = fav[id];
    const title =
      typeof data === "object" && data && data.title
        ? data.title
        : "Рецепт #" + id;
    const category =
      typeof data === "object" && data && data.category_lvl1
        ? data.category_lvl1
        : "";
    const url = typeof data === "object" && data && data.url ? data.url : "";

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
    if (url) {
      const linkEl = document.createElement("a");
      linkEl.href = url;
      linkEl.target = "_blank";
      linkEl.rel = "noopener noreferrer";
      linkEl.className = "badge";
      linkEl.textContent = "Открыть рецепт";
      linkEl.style.marginTop = "4px";
      linkEl.style.display = "inline-block";
      info.appendChild(linkEl);
    }

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "Удалить из избранного";
    removeBtn.className = "primary-btn primary-btn--ghost primary-btn--sm";
    removeBtn.addEventListener("click", () => removeFromFavorites(id));

    row.appendChild(info);
    row.appendChild(removeBtn);
    card.appendChild(row);
    container.appendChild(card);
  });
}

document.addEventListener("DOMContentLoaded", renderFavoritesList);
