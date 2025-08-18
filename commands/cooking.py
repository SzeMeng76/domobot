# commands/cooking.py

import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.config_manager import get_config
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_error, send_success
from utils.permissions import Permission
from utils.session_manager import app_search_sessions as recipe_search_sessions

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None

# ID映射缓存 - 用于解决callback_data长度限制
recipe_id_mapping = {}
mapping_counter = 0

def set_dependencies(cm):
    """初始化依赖"""
    global cache_manager
    cache_manager = cm

def get_short_recipe_id(full_recipe_id: str) -> str:
    """获取短菜谱ID用于callback_data"""
    global recipe_id_mapping, mapping_counter
    
    # 查找是否已存在映射
    for short_id, full_id in recipe_id_mapping.items():
        if full_id == full_recipe_id:
            return short_id
    
    # 创建新的短ID
    mapping_counter += 1
    short_id = str(mapping_counter)
    recipe_id_mapping[short_id] = full_recipe_id
    
    # 清理过多的映射（保持最近1000个）
    if len(recipe_id_mapping) > 1000:
        # 删除前100个旧映射
        old_keys = list(recipe_id_mapping.keys())[:100]
        for key in old_keys:
            del recipe_id_mapping[key]
    
    return short_id

def get_full_recipe_id(short_recipe_id: str) -> Optional[str]:
    """根据短ID获取完整菜谱ID"""
    return recipe_id_mapping.get(short_recipe_id)

class CookingService:
    """烹饪菜谱服务类"""
    
    RECIPES_URL = "https://weilei.site/all_recipes.json"
    
    def __init__(self):
        self.recipes_data = []
        self.categories = []
        self.last_fetch_time = 0
        self.cache_duration = 24 * 3600  # 24小时缓存
        
    async def _fetch_recipes_data(self) -> List[Dict[str, Any]]:
        """从远程URL获取菜谱数据"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        try:
            from utils.http_client import create_custom_client
            
            async with create_custom_client(headers=headers) as client:
                response = await client.get(self.RECIPES_URL, timeout=30.0)
                response.raise_for_status()
                data = response.json()
                logger.info(f"成功获取 {len(data)} 个菜谱数据")
                return data
        except httpx.RequestError as e:
            logger.error(f"获取菜谱数据失败: {e}")
            return []
        except Exception as e:
            logger.error(f"解析菜谱数据异常: {e}")
            return []
            
    async def load_recipes_data(self, force_refresh: bool = False) -> bool:
        """加载菜谱数据（带缓存）"""
        current_time = datetime.now().timestamp()
        
        # 检查是否需要刷新缓存
        if not force_refresh and self.recipes_data and (current_time - self.last_fetch_time < self.cache_duration):
            return True
            
        # 尝试从Redis缓存获取
        if cache_manager and not force_refresh:
            try:
                cached_data = await cache_manager.get("cooking:recipes_data")
                if cached_data:
                    self.recipes_data = json.loads(cached_data)
                    self.categories = list(set(recipe.get("category", "其他") for recipe in self.recipes_data))
                    self.last_fetch_time = current_time
                    logger.info(f"从缓存加载 {len(self.recipes_data)} 个菜谱")
                    return True
            except Exception as e:
                logger.warning(f"从缓存加载菜谱数据失败: {e}")
        
        # 从网络获取新数据
        data = await self._fetch_recipes_data()
        if not data:
            logger.error("无法获取菜谱数据")
            return False
            
        self.recipes_data = data
        self.categories = list(set(recipe.get("category", "其他") for recipe in data))
        self.last_fetch_time = current_time
        
        # 保存到Redis缓存
        if cache_manager:
            try:
                await cache_manager.set("cooking:recipes_data", json.dumps(data), ttl=self.cache_duration)
                logger.info("菜谱数据已保存到缓存")
            except Exception as e:
                logger.warning(f"保存菜谱数据到缓存失败: {e}")
                
        return True
        
    def search_recipes(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索菜谱"""
        if not self.recipes_data:
            return []
            
        query_lower = query.lower()
        results = []
        
        for recipe in self.recipes_data:
            # 搜索菜谱名称
            if query_lower in recipe.get("name", "").lower():
                results.append(recipe)
            # 搜索食材
            elif any(query_lower in ingredient.get("name", "").lower() 
                    for ingredient in recipe.get("ingredients", [])):
                results.append(recipe)
            # 搜索标签
            elif any(query_lower in tag.lower() for tag in recipe.get("tags", [])):
                results.append(recipe)
                
        return results[:limit]
        
    def get_recipes_by_category(self, category: str, limit: int = 10) -> List[Dict[str, Any]]:
        """按分类获取菜谱"""
        if not self.recipes_data:
            return []
            
        results = [recipe for recipe in self.recipes_data 
                  if recipe.get("category", "") == category]
        return results[:limit]
        
    def get_random_recipes(self, count: int = 5) -> List[Dict[str, Any]]:
        """获取随机菜谱"""
        if not self.recipes_data:
            return []
            
        return random.sample(self.recipes_data, min(count, len(self.recipes_data)))
        
    def get_recipe_by_id(self, recipe_id: str) -> Optional[Dict[str, Any]]:
        """根据ID获取菜谱详情"""
        for recipe in self.recipes_data:
            if recipe.get("id") == recipe_id:
                return recipe
        return None
        
    def recommend_meals(self, people_count: int, allergies: List[str] = None, 
                       avoid_items: List[str] = None) -> Dict[str, Any]:
        """智能膳食推荐"""
        if not self.recipes_data:
            return {"dishes": [], "message": "暂无菜谱数据"}
            
        allergies = allergies or []
        avoid_items = avoid_items or []
        
        # 过滤掉含有过敏原和忌口食材的菜谱
        filtered_recipes = []
        for recipe in self.recipes_data:
            has_allergen = False
            for ingredient in recipe.get("ingredients", []):
                ingredient_name = ingredient.get("name", "").lower()
                if any(allergy.lower() in ingredient_name for allergy in allergies):
                    has_allergen = True
                    break
                if any(avoid.lower() in ingredient_name for avoid in avoid_items):
                    has_allergen = True
                    break
            if not has_allergen:
                filtered_recipes.append(recipe)
                
        if not filtered_recipes:
            return {"dishes": [], "message": "根据您的要求未找到合适的菜谱"}
            
        # 根据人数推荐菜品数量
        dish_count = max(2, min(6, people_count))
        
        # 尝试平衡不同分类的菜品
        categories = ["荤菜", "素菜", "主食", "汤羹", "水产"]
        recommended = []
        
        for category in categories:
            category_recipes = [r for r in filtered_recipes if r.get("category") == category]
            if category_recipes and len(recommended) < dish_count:
                recommended.append(random.choice(category_recipes))
                
        # 如果还不够，随机添加
        remaining_count = dish_count - len(recommended)
        if remaining_count > 0:
            remaining_recipes = [r for r in filtered_recipes if r not in recommended]
            if remaining_recipes:
                recommended.extend(random.sample(remaining_recipes, 
                                               min(remaining_count, len(remaining_recipes))))
                
        return {
            "dishes": recommended,
            "message": f"为{people_count}人推荐{len(recommended)}道菜"
        }

# 初始化服务实例
cooking_service = CookingService()

async def recipe_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """菜谱搜索命令 /recipe"""
    if not update.message:
        return
        
    # 检查参数
    if not context.args:
        help_text = """🍳 菜谱搜索帮助

使用方法:
• /recipe 红烧肉 - 搜索菜谱
• /recipe_category 荤菜 - 按分类查看
• /recipe_random - 随机菜谱  
• /what_to_eat 4 - 今天吃什么
• /meal_plan 3 虾 香菜 - 智能推荐

📋 可用分类: 荤菜、素菜、主食、汤羹、水产、早餐、甜品等
        """
        await send_success(context, update.message.chat_id, foldable_text_with_markdown_v2(help_text))
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
        
    query = " ".join(context.args)
    
    # 显示加载消息
    loading_message = f"🔍 正在搜索菜谱: {query}... ⏳"
    message = await context.bot.send_message(
        chat_id=update.message.chat_id, 
        text=foldable_text_v2(loading_message), 
        parse_mode="MarkdownV2"
    )
    
    try:
        # 加载菜谱数据
        if not await cooking_service.load_recipes_data():
            await message.edit_text(foldable_text_v2("❌ 无法获取菜谱数据，请稍后重试"), parse_mode="MarkdownV2")
            return
            
        # 搜索菜谱
        results = cooking_service.search_recipes(query, limit=10)
        
        if not results:
            await message.edit_text(foldable_text_v2(f"❌ 未找到关于 '{query}' 的菜谱"), parse_mode="MarkdownV2")
            return
            
        # 创建inline按钮
        keyboard = []
        for i, recipe in enumerate(results[:8]):  # 限制8个按钮
            recipe_name = recipe.get("name", "未知菜谱")
            recipe_id = recipe.get("id", str(i))
            short_id = get_short_recipe_id(recipe_id)
            button = InlineKeyboardButton(
                text=f"🍽️ {recipe_name}",
                callback_data=f"recipe_detail:{short_id}"
            )
            keyboard.append([button])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        result_text = f"🔍 搜索结果 ({len(results)} 个菜谱)\n\n请点击下方按钮查看详细信息:"
        
        await message.edit_text(
            text=foldable_text_with_markdown_v2(result_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
        # 保存搜索会话
        session_key = f"{update.message.chat_id}_{message.message_id}"
        recipe_search_sessions[session_key] = {
            "results": results,
            "query": query,
            "timestamp": datetime.now().timestamp()
        }
        
        # 安排删除用户命令
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        
    except Exception as e:
        logger.error(f"搜索菜谱时发生错误: {e}", exc_info=True)
        await message.edit_text(foldable_text_v2(f"❌ 搜索时发生错误: {str(e)}"), parse_mode="MarkdownV2")

async def recipe_category_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """按分类查看菜谱 /recipe_category"""
    if not update.message:
        return
        
    # 如果有参数，直接处理
    if context.args:
        category = " ".join(context.args)
        await _execute_category_search(update, context, category)
        return
    
    # 没有参数，显示分类选择按钮
    loading_message = "📋 正在加载分类信息... ⏳"
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    
    try:
        if not await cooking_service.load_recipes_data():
            await message.edit_text(foldable_text_v2("❌ 无法获取分类信息"), parse_mode="MarkdownV2")
            return
            
        # 创建分类按钮 - 4列布局更紧凑
        categories = sorted(cooking_service.categories)
        keyboard = []
        
        # 分类按钮映射（使用emoji让按钮更直观）
        category_emojis = {
            "主食": "🍚",
            "荤菜": "🥩", 
            "素菜": "🥬",
            "水产": "🐟",
            "汤": "🍲",
            "早餐": "🥐",
            "甜品": "🍰",
            "饮品": "🥤",
            "调料": "🧂",
            "半成品加工": "📦"
        }
        
        # 按4个一行排列
        for i in range(0, len(categories), 3):
            row = []
            for j in range(3):
                if i + j < len(categories):
                    cat = categories[i + j]
                    emoji = category_emojis.get(cat, "📋")
                    button = InlineKeyboardButton(
                        text=f"{emoji} {cat}",
                        callback_data=f"recipe_category_select:{cat}"
                    )
                    row.append(button)
            keyboard.append(row)
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = "📋 菜谱分类\n\n请选择要查看的分类:"
        
        await message.edit_text(
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        
    except Exception as e:
        logger.error(f"加载分类信息时发生错误: {e}", exc_info=True)
        await message.edit_text(foldable_text_v2(f"❌ 加载时发生错误: {str(e)}"), parse_mode="MarkdownV2")

async def _execute_category_search(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str, query: CallbackQuery = None) -> None:
    """执行分类搜索"""
    loading_message = f"🔍 正在查找 {category} 分类的菜谱... ⏳"
    
    if query:
        # 来自callback，编辑消息
        await query.edit_message_text(
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
        message = query.message
    else:
        # 来自命令，发送新消息
        message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
    
    try:
        if not await cooking_service.load_recipes_data():
            text = foldable_text_v2("❌ 无法获取菜谱数据")
            if query:
                await query.edit_message_text(text, parse_mode="MarkdownV2")
            else:
                await message.edit_text(text, parse_mode="MarkdownV2")
            return
            
        results = cooking_service.get_recipes_by_category(category, limit=10)
        
        if not results:
            text = foldable_text_v2(f"❌ '{category}' 分类下没有找到菜谱")
            if query:
                await query.edit_message_text(text, parse_mode="MarkdownV2")
            else:
                await message.edit_text(text, parse_mode="MarkdownV2")
            return
            
        # 创建inline按钮
        keyboard = []
        for recipe in results[:8]:
            recipe_name = recipe.get("name", "未知菜谱")
            recipe_id = recipe.get("id", "")
            short_id = get_short_recipe_id(recipe_id)
            button = InlineKeyboardButton(
                text=f"🍽️ {recipe_name}",
                callback_data=f"recipe_detail:{short_id}"
            )
            keyboard.append([button])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        result_text = f"📋 {category} ({len(results)} 个菜谱)\n\n请点击下方按钮查看详细信息:"
        
        if query:
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            await message.edit_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        
    except Exception as e:
        logger.error(f"查询分类菜谱时发生错误: {e}", exc_info=True)
        error_text = foldable_text_v2(f"❌ 查询时发生错误: {str(e)}")
        if query:
            await query.edit_message_text(error_text, parse_mode="MarkdownV2")
        else:
            await message.edit_text(error_text, parse_mode="MarkdownV2")

async def recipe_random_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """随机菜谱推荐 /recipe_random"""
    if not update.message:
        return
        
    loading_message = "🎲 正在为您随机挑选菜谱... ⏳"
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    
    try:
        if not await cooking_service.load_recipes_data():
            await message.edit_text(foldable_text_v2("❌ 无法获取菜谱数据"), parse_mode="MarkdownV2")
            return
            
        results = cooking_service.get_random_recipes(count=6)
        
        if not results:
            await message.edit_text(foldable_text_v2("❌ 暂无菜谱数据"), parse_mode="MarkdownV2")
            return
            
        # 创建inline按钮
        keyboard = []
        for recipe in results:
            recipe_name = recipe.get("name", "未知菜谱")
            recipe_id = recipe.get("id", "")
            short_id = get_short_recipe_id(recipe_id)
            button = InlineKeyboardButton(
                text=f"🍽️ {recipe_name}",
                callback_data=f"recipe_detail:{short_id}"
            )
            keyboard.append([button])
            
        # 添加重新随机按钮
        keyboard.append([InlineKeyboardButton("🎲 重新随机", callback_data="recipe_random_again")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        result_text = f"🎲 随机推荐 ({len(results)} 个菜谱)\n\n请点击下方按钮查看详细信息:"
        
        await message.edit_text(
            text=foldable_text_with_markdown_v2(result_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        
    except Exception as e:
        logger.error(f"随机推荐菜谱时发生错误: {e}", exc_info=True)
        await message.edit_text(foldable_text_v2(f"❌ 推荐时发生错误: {str(e)}"), parse_mode="MarkdownV2")

async def what_to_eat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """今天吃什么 /what_to_eat"""
    if not update.message:
        return
        
    # 如果有参数，直接处理
    if context.args:
        try:
            people_count = int(context.args[0])
            people_count = max(1, min(10, people_count))  # 限制1-10人
            await _execute_what_to_eat(update, context, people_count)
            return
        except ValueError:
            pass
    
    # 没有参数，显示人数选择按钮
    keyboard = []
    # 第一行：1-3人
    row1 = [
        InlineKeyboardButton("1️⃣ 1人", callback_data="what_to_eat_select:1"),
        InlineKeyboardButton("2️⃣ 2人", callback_data="what_to_eat_select:2"),
        InlineKeyboardButton("3️⃣ 3人", callback_data="what_to_eat_select:3")
    ]
    keyboard.append(row1)
    
    # 第二行：4-6人
    row2 = [
        InlineKeyboardButton("4️⃣ 4人", callback_data="what_to_eat_select:4"),
        InlineKeyboardButton("5️⃣ 5人", callback_data="what_to_eat_select:5"),
        InlineKeyboardButton("6️⃣ 6人", callback_data="what_to_eat_select:6")
    ]
    keyboard.append(row2)
    
    # 第三行：7-10人
    row3 = [
        InlineKeyboardButton("7️⃣ 7人", callback_data="what_to_eat_select:7"),
        InlineKeyboardButton("8️⃣ 8人", callback_data="what_to_eat_select:8"),
        InlineKeyboardButton("🔟 更多", callback_data="what_to_eat_select:10")
    ]
    keyboard.append(row3)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = "🍽️ 今天吃什么？\n\n请选择用餐人数:"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )
    
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

async def _execute_what_to_eat(update: Update, context: ContextTypes.DEFAULT_TYPE, people_count: int, query: CallbackQuery = None) -> None:
    """执行今天吃什么推荐"""
    loading_message = f"🤔 正在为 {people_count} 人推荐今日菜单... ⏳"
    
    if query:
        # 来自callback，编辑消息
        await query.edit_message_text(
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
        message = query.message
    else:
        # 来自命令，发送新消息
        message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
    
    try:
        if not await cooking_service.load_recipes_data():
            text = foldable_text_v2("❌ 无法获取菜谱数据")
            if query:
                await query.edit_message_text(text, parse_mode="MarkdownV2")
            else:
                await message.edit_text(text, parse_mode="MarkdownV2")
            return
            
        # 智能推荐
        recommendation = cooking_service.recommend_meals(people_count)
        dishes = recommendation["dishes"]
        
        if not dishes:
            text = foldable_text_v2("❌ 暂无合适的菜谱推荐")
            if query:
                await query.edit_message_text(text, parse_mode="MarkdownV2")
            else:
                await message.edit_text(text, parse_mode="MarkdownV2")
            return
            
        # 创建inline按钮
        keyboard = []
        for dish in dishes:
            dish_name = dish.get("name", "未知菜谱")
            dish_id = dish.get("id", "")
            short_id = get_short_recipe_id(dish_id)
            category = dish.get("category", "")
            button = InlineKeyboardButton(
                text=f"🍽️ {dish_name} ({category})",
                callback_data=f"recipe_detail:{short_id}"
            )
            keyboard.append([button])
            
        # 添加重新推荐按钮
        keyboard.append([InlineKeyboardButton("🔄 重新推荐", callback_data=f"what_to_eat_again:{people_count}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        result_text = f"🍽️ 今日推荐 ({people_count}人份)\n\n{recommendation['message']}，请点击查看详情:"
        
        if query:
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            await message.edit_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        
    except Exception as e:
        logger.error(f"推荐今日菜单时发生错误: {e}", exc_info=True)
        error_text = foldable_text_v2(f"❌ 推荐时发生错误: {str(e)}")
        if query:
            await query.edit_message_text(error_text, parse_mode="MarkdownV2")
        else:
            await message.edit_text(error_text, parse_mode="MarkdownV2")

async def meal_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """智能膳食推荐 /meal_plan"""
    if not update.message:
        return
        
    if not context.args:
        help_text = """🧩 智能膳食推荐

使用方法:
/meal_plan 人数 [过敏原] [忌口食材]

示例:
• /meal_plan 3 - 为3人推荐
• /meal_plan 4 虾 蟹 - 4人，对虾蟹过敏
• /meal_plan 2 花生 香菜 葱 - 2人，过敏花生，忌口香菜葱

系统会根据人数和饮食限制智能推荐合适的菜品组合。
        """
        await send_success(context, update.message.chat_id, foldable_text_with_markdown_v2(help_text))
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
        
    # 解析参数
    try:
        people_count = int(context.args[0])
        people_count = max(1, min(10, people_count))
        allergies_and_avoid = context.args[1:] if len(context.args) > 1 else []
        
        # 简单处理：将所有额外参数视为过敏原和忌口
        allergies = allergies_and_avoid[:2] if len(allergies_and_avoid) >= 2 else []
        avoid_items = allergies_and_avoid[2:] if len(allergies_and_avoid) > 2 else []
        
    except (ValueError, IndexError):
        await send_error(context, update.message.chat_id, 
                        foldable_text_v2("❌ 参数格式错误，请使用: /meal_plan 人数 [过敏原] [忌口]"))
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
        
    # 构建加载消息
    restrictions = []
    if allergies:
        restrictions.append(f"过敏: {', '.join(allergies)}")
    if avoid_items:
        restrictions.append(f"忌口: {', '.join(avoid_items)}")
    restrictions_text = f" ({'; '.join(restrictions)})" if restrictions else ""
    
    loading_message = f"🧩 正在为 {people_count} 人智能推荐膳食{restrictions_text}... ⏳"
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    
    try:
        if not await cooking_service.load_recipes_data():
            await message.edit_text(foldable_text_v2("❌ 无法获取菜谱数据"), parse_mode="MarkdownV2")
            return
            
        # 智能推荐
        recommendation = cooking_service.recommend_meals(people_count, allergies, avoid_items)
        dishes = recommendation["dishes"]
        
        if not dishes:
            await message.edit_text(
                foldable_text_v2(f"❌ {recommendation['message']}，请尝试减少限制条件"),
                parse_mode="MarkdownV2"
            )
            return
            
        # 创建inline按钮
        keyboard = []
        for dish in dishes:
            dish_name = dish.get("name", "未知菜谱")
            dish_id = dish.get("id", "")
            short_id = get_short_recipe_id(dish_id)
            category = dish.get("category", "")
            difficulty = "★" * dish.get("difficulty", 1)
            button = InlineKeyboardButton(
                text=f"🍽️ {dish_name} ({category}) {difficulty}",
                callback_data=f"recipe_detail:{short_id}"
            )
            keyboard.append([button])
            
        # 添加重新推荐按钮
        callback_data = f"meal_plan_again:{people_count}:{','.join(allergies)}:{','.join(avoid_items)}"
        keyboard.append([InlineKeyboardButton("🔄 重新推荐", callback_data=callback_data)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        result_text = f"🧩 智能膳食推荐\n\n{recommendation['message']}{restrictions_text}\n\n请点击查看详细信息:"
        
        await message.edit_text(
            text=foldable_text_with_markdown_v2(result_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        
    except Exception as e:
        logger.error(f"智能膳食推荐时发生错误: {e}", exc_info=True)
        await message.edit_text(foldable_text_v2(f"❌ 推荐时发生错误: {str(e)}"), parse_mode="MarkdownV2")

async def cooking_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """清理烹饪模块缓存 /cooking_cleancache"""
    if not update.message:
        return
        
    try:
        if cache_manager:
            await cache_manager.delete("cooking:recipes_data")
            cooking_service.recipes_data = []
            cooking_service.categories = []
            cooking_service.last_fetch_time = 0
            
        success_message = "✅ 烹饪模块缓存已清理"
        await send_success(context, update.message.chat_id, foldable_text_v2(success_message))
        
    except Exception as e:
        logger.error(f"清理缓存时发生错误: {e}", exc_info=True)
        error_message = f"❌ 清理缓存失败: {str(e)}"
        await send_error(context, update.message.chat_id, foldable_text_v2(error_message))
        
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

def format_recipe_detail(recipe: Dict[str, Any]) -> str:
    """格式化菜谱详情"""
    name = recipe.get("name", "未知菜谱")
    description = recipe.get("description", "暂无描述")
    category = recipe.get("category", "其他")
    difficulty = "★" * recipe.get("difficulty", 1)
    servings = recipe.get("servings", 2)
    
    # 时间信息
    prep_time = recipe.get("prep_time_minutes")
    cook_time = recipe.get("cook_time_minutes")
    total_time = recipe.get("total_time_minutes")
    
    time_info = []
    if prep_time:
        time_info.append(f"准备 {prep_time}分钟")
    if cook_time:
        time_info.append(f"烹饪 {cook_time}分钟")
    if total_time:
        time_info.append(f"总计 {total_time}分钟")
    time_text = " | ".join(time_info) if time_info else "时间未知"
    
    # 食材列表 - 清理格式
    ingredients = recipe.get("ingredients", [])
    ingredients_list = []
    for ing in ingredients[:15]:  # 增加到15个食材
        name = ing.get('name', '').strip()
        text_quantity = ing.get('text_quantity', '').strip()
        
        # 跳过空的或无效的食材
        if not name or name == "--":
            continue
            
        if text_quantity and text_quantity != "--":
            ingredients_list.append(f"• {text_quantity} {name}")
        else:
            ingredients_list.append(f"• {name}")
    
    ingredients_text = "\n".join(ingredients_list) if ingredients_list else "• 暂无详细食材信息"
    
    if len(ingredients) > 15:
        ingredients_text += f"\n• ... 等{len(ingredients)}种食材"
    
    # 制作步骤 - 修复转义和数据问题
    steps = recipe.get("steps", [])
    steps_list = []
    for i, step in enumerate(steps[:10]):  # 增加到10个步骤
        step_num = step.get('step', i+1)
        description = step.get('description', '').strip()
        
        # 跳过空的或无效的步骤
        if not description or description == "--":
            continue
            
        steps_list.append(f"{step_num}. {description}")
    
    steps_text = "\n".join(steps_list) if steps_list else "暂无详细制作步骤"
    
    if len(steps) > 10:
        steps_text += f"\n... 等{len(steps)}个步骤"
    
    # 标签 - 过滤无效标签
    tags = recipe.get("tags", [])
    valid_tags = [tag for tag in tags[:5] if tag and tag.strip() and tag != "--"]
    tags_text = " ".join([f"#{tag}" for tag in valid_tags]) if valid_tags else "无标签"
    
    # 构建最终文本，避免手动转义
    result = f"""🍽️ {name}

📝 简介: {description}

📋 信息:
• 分类: {category}
• 难度: {difficulty}
• 份量: {servings}人份
• 时间: {time_text}

🥕 食材:
{ingredients_text}

👨‍🍳 步骤:
{steps_text}

🏷️ 标签: {tags_text}
"""
    
    return result

# =============================================================================
# Callback 处理器
# =============================================================================

async def recipe_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理菜谱详情按钮点击"""
    query = update.callback_query
    await query.answer()
    
    if not query or not query.data:
        return
        
    try:
        callback_data = query.data
        if callback_data.startswith("recipe_detail:"):
            short_id = callback_data.replace("recipe_detail:", "")
            recipe_id = get_full_recipe_id(short_id)
            if not recipe_id:
                await query.edit_message_text(
                    foldable_text_v2("❌ 菜谱信息已过期，请重新搜索"),
                    parse_mode="MarkdownV2"
                )
                return
            
            # 确保数据已加载
            if not await cooking_service.load_recipes_data():
                await query.edit_message_text(
                    foldable_text_v2("❌ 无法获取菜谱数据"),
                    parse_mode="MarkdownV2"
                )
                return
                
            # 获取菜谱详情
            recipe = cooking_service.get_recipe_by_id(recipe_id)
            if not recipe:
                await query.edit_message_text(
                    foldable_text_v2("❌ 未找到指定菜谱"),
                    parse_mode="MarkdownV2"
                )
                return
                
            # 格式化详情
            detail_text = format_recipe_detail(recipe)
            
            # 菜谱详情是最终结果，不需要返回按钮，消息会自动删除
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(detail_text),
                parse_mode="MarkdownV2"
            )
            
    except Exception as e:
        logger.error(f"处理菜谱详情回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def recipe_random_again_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理重新随机按钮点击"""
    query = update.callback_query
    await query.answer("🎲 正在重新随机...")
    
    if not query:
        return
        
    try:
        # 确保数据已加载
        if not await cooking_service.load_recipes_data():
            await query.edit_message_text(
                foldable_text_v2("❌ 无法获取菜谱数据"),
                parse_mode="MarkdownV2"
            )
            return
            
        # 获取新的随机菜谱
        results = cooking_service.get_random_recipes(count=6)
        
        if not results:
            await query.edit_message_text(
                foldable_text_v2("❌ 暂无菜谱数据"),
                parse_mode="MarkdownV2"
            )
            return
            
        # 创建新的按钮
        keyboard = []
        for recipe in results:
            recipe_name = recipe.get("name", "未知菜谱")
            recipe_id = recipe.get("id", "")
            short_id = get_short_recipe_id(recipe_id)
            button = InlineKeyboardButton(
                text=f"🍽️ {recipe_name}",
                callback_data=f"recipe_detail:{short_id}"
            )
            keyboard.append([button])
            
        # 添加重新随机按钮
        keyboard.append([InlineKeyboardButton("🎲 重新随机", callback_data="recipe_random_again")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        result_text = f"🎲 随机推荐 ({len(results)} 个菜谱)\n\n请点击下方按钮查看详细信息:"
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(result_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"处理重新随机回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def recipe_category_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理分类选择按钮点击"""
    query = update.callback_query
    await query.answer()
    
    if not query or not query.data:
        return
        
    try:
        callback_data = query.data
        if callback_data.startswith("recipe_category_select:"):
            category = callback_data.replace("recipe_category_select:", "")
            
            # 直接执行分类搜索
            await _execute_category_search(update, context, category, query)
            
    except Exception as e:
        logger.error(f"处理分类选择回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def what_to_eat_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理人数选择按钮点击"""
    query = update.callback_query
    await query.answer()
    
    if not query or not query.data:
        return
        
    try:
        callback_data = query.data
        if callback_data.startswith("what_to_eat_select:"):
            people_count_str = callback_data.replace("what_to_eat_select:", "")
            people_count = int(people_count_str)
            
            # 直接执行推荐
            await _execute_what_to_eat(update, context, people_count, query)
            
    except Exception as e:
        logger.error(f"处理人数选择回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def what_to_eat_again_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理重新推荐今日菜单按钮点击"""
    query = update.callback_query
    await query.answer("🔄 正在重新推荐...")
    
    if not query or not query.data:
        return
        
    try:
        callback_data = query.data
        if callback_data.startswith("what_to_eat_again:"):
            people_count_str = callback_data.replace("what_to_eat_again:", "")
            people_count = int(people_count_str)
            
            # 确保数据已加载
            if not await cooking_service.load_recipes_data():
                await query.edit_message_text(
                    foldable_text_v2("❌ 无法获取菜谱数据"),
                    parse_mode="MarkdownV2"
                )
                return
                
            # 重新推荐
            recommendation = cooking_service.recommend_meals(people_count)
            dishes = recommendation["dishes"]
            
            if not dishes:
                await query.edit_message_text(
                    foldable_text_v2("❌ 暂无合适的菜谱推荐"),
                    parse_mode="MarkdownV2"
                )
                return
                
            # 创建新的按钮
            keyboard = []
            for dish in dishes:
                dish_name = dish.get("name", "未知菜谱")
                dish_id = dish.get("id", "")
                short_id = get_short_recipe_id(dish_id)
                category = dish.get("category", "")
                button = InlineKeyboardButton(
                    text=f"🍽️ {dish_name} ({category})",
                    callback_data=f"recipe_detail:{short_id}"
                )
                keyboard.append([button])
                
            # 添加重新推荐按钮
            keyboard.append([InlineKeyboardButton("🔄 重新推荐", callback_data=f"what_to_eat_again:{people_count}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            result_text = f"🍽️ 今日推荐 ({people_count}人份)\n\n{recommendation['message']}，请点击查看详情:"
            
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"处理重新推荐回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def meal_plan_again_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理重新智能推荐按钮点击"""
    query = update.callback_query
    await query.answer("🔄 正在重新智能推荐...")
    
    if not query or not query.data:
        return
        
    try:
        callback_data = query.data
        if callback_data.startswith("meal_plan_again:"):
            parts = callback_data.replace("meal_plan_again:", "").split(":")
            people_count = int(parts[0])
            allergies = parts[1].split(",") if parts[1] else []
            avoid_items = parts[2].split(",") if parts[2] else []
            
            # 过滤空值
            allergies = [a for a in allergies if a.strip()]
            avoid_items = [a for a in avoid_items if a.strip()]
            
            # 确保数据已加载
            if not await cooking_service.load_recipes_data():
                await query.edit_message_text(
                    foldable_text_v2("❌ 无法获取菜谱数据"),
                    parse_mode="MarkdownV2"
                )
                return
                
            # 重新智能推荐
            recommendation = cooking_service.recommend_meals(people_count, allergies, avoid_items)
            dishes = recommendation["dishes"]
            
            if not dishes:
                await query.edit_message_text(
                    foldable_text_v2(f"❌ {recommendation['message']}，请尝试减少限制条件"),
                    parse_mode="MarkdownV2"
                )
                return
                
            # 创建新的按钮
            keyboard = []
            for dish in dishes:
                dish_name = dish.get("name", "未知菜谱")
                dish_id = dish.get("id", "")
                short_id = get_short_recipe_id(dish_id)
                category = dish.get("category", "")
                difficulty = "★" * dish.get("difficulty", 1)
                button = InlineKeyboardButton(
                    text=f"🍽️ {dish_name} ({category}) {difficulty}",
                    callback_data=f"recipe_detail:{short_id}"
                )
                keyboard.append([button])
                
            # 添加重新推荐按钮
            callback_data = f"meal_plan_again:{people_count}:{','.join(allergies)}:{','.join(avoid_items)}"
            keyboard.append([InlineKeyboardButton("🔄 重新推荐", callback_data=callback_data)])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 构建限制条件文本
            restrictions = []
            if allergies:
                restrictions.append(f"过敏: {', '.join(allergies)}")
            if avoid_items:
                restrictions.append(f"忌口: {', '.join(avoid_items)}")
            restrictions_text = f" ({'; '.join(restrictions)})" if restrictions else ""
            
            result_text = f"🧩 智能膳食推荐\n\n{recommendation['message']}{restrictions_text}\n\n请点击查看详细信息:"
            
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"处理重新智能推荐回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

# back_to_search_callback 已删除，因为菜谱详情是最终结果，消息会自动删除

# =============================================================================
# 注册命令和回调
# =============================================================================

# 注册命令
command_factory.register_command("recipe", recipe_search_command, permission=Permission.NONE, description="菜谱搜索")
command_factory.register_command("recipe_category", recipe_category_command, permission=Permission.NONE, description="按分类查看菜谱")
command_factory.register_command("recipe_random", recipe_random_command, permission=Permission.NONE, description="随机菜谱推荐")
command_factory.register_command("what_to_eat", what_to_eat_command, permission=Permission.NONE, description="今天吃什么")
command_factory.register_command("meal_plan", meal_plan_command, permission=Permission.NONE, description="智能膳食推荐")
command_factory.register_command("cooking_cleancache", cooking_clean_cache_command, permission=Permission.ADMIN, description="清理烹饪模块缓存")

# 注册回调处理器
command_factory.register_callback(r"^recipe_detail:", recipe_detail_callback, permission=Permission.NONE, description="菜谱详情")
command_factory.register_callback(r"^recipe_random_again$", recipe_random_again_callback, permission=Permission.NONE, description="重新随机推荐")
command_factory.register_callback(r"^recipe_category_select:", recipe_category_select_callback, permission=Permission.NONE, description="选择菜谱分类")
command_factory.register_callback(r"^what_to_eat_select:", what_to_eat_select_callback, permission=Permission.NONE, description="选择用餐人数")
command_factory.register_callback(r"^what_to_eat_again:", what_to_eat_again_callback, permission=Permission.NONE, description="重新推荐今日菜单")
command_factory.register_callback(r"^meal_plan_again:", meal_plan_again_callback, permission=Permission.NONE, description="重新智能推荐")