import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
from operator import itemgetter

from helpers import apology, login_required, lookup, usd, table_name

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")
# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    # Getting the cash in holding of the user
    user = db.execute("SELECT cash FROM users WHERE id=:id", id=session["user_id"])[0]
    cash = float(user["cash"])
    total_money = cash

    # Getting the stocks owned by the user
    stocks = db.execute("SELECT * FROM :name", name=table_name(session["user_id"]))

    # Iterating over each stock
    for stock in stocks:
        # Getting the stock info
        info = lookup(stock["symbol"])

        stock["name"] = info["name"]
        stock["price"] = info["price"]
        total_money += info["price"]*stock["shares"]

    return render_template("index.html", stocks = stocks, cash = cash, total = total_money)


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        stock = lookup(request.form.get("symbol"))
        if stock == None:
            flash("Stock not found", "danger")
            return render_template("quote.html")
        return render_template("quoted.html", name=stock["name"], price=stock["price"])
    else:
        return render_template("quote.html")


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        """Validation"""
        if not request.form.get("symbol"):
            flash("Must enter a stock symbol", "danger")
            return render_template("buy.html")

        stock = lookup(request.form.get("symbol"))
        if stock == None:
            flash("Stock not found", "danger")
            return render_template("buy.html")

        if int(request.form.get("shares")) <= 0:
            flash("Must enter a valid number of shares", "danger")
            return render_template("buy.html")

        """Make changes in the database"""
        rows = db.execute("SELECT cash FROM users WHERE id=?", session["user_id"])
        cash = rows[0]["cash"]

        stock_amt = float(request.form.get("shares"))*stock["price"]
        if cash < stock_amt:
            flash("Not enough cash", "danger")
            return render_template("buy.html")

        # Update cash amount to reflect bought shares
        db.execute("UPDATE users SET cash=? WHERE id=?", cash-stock_amt, session["user_id"])

        # Log transaction
        db.execute("INSERT INTO stock_info (user_id, symbol, name, shares, price) VALUES (:user_id, :symbol, :name, :shares, :price)"
                    , user_id=session["user_id"], symbol=stock["symbol"], name=stock["name"]
                    , shares=request.form.get("shares"), price=stock["price"])

        # Add stock
        current = db.execute("SELECT * FROM :name WHERE symbol=:symbol", name=table_name(session["user_id"]), symbol=stock["symbol"])

        if len(current) == 0:
            db.execute("INSERT INTO :name (symbol, shares, avg, total_bought) VALUES (:symbol, :shares, :avg, :total_bought)"
                        , name=table_name(session["user_id"])
                        , symbol = stock["symbol"]
                        , shares = request.form.get("shares")
                        , avg = float(stock["price"])
                        , total_bought = stock_amt)
        else:
            db.execute("UPDATE :name SET shares=shares + :shares, avg=:avg, total_bought=total_bought + :value"
                        , name=table_name(session["user_id"])
                        , shares = int(request.form.get("shares"))
                        , avg = (current[0]["total_bought"] + stock_amt)/float(current[0]["shares"] + int(request.form.get("shares")))
                        , value = stock_amt)

        flash(f"Bought {request.form.get('shares')} shares of {stock['symbol']}", "success")

        return redirect("/")
    else:
        return render_template("buy.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Get all the stocks of the user"""
    stocks = db.execute("SELECT symbol FROM :name", name=table_name(session["user_id"]))

    """Sell shares of stock"""
    if request.method == "POST":
        """Validation"""
        symbol = request.form.get("symbol")
        if not request.form.get("symbol"):
            flash("Please select a stock to sell", "danger")
            return render_template("sell.html", stocks=stocks)

        stock = db.execute("SELECT * FROM :name WHERE symbol=:symbol", name=table_name(session["user_id"]), symbol=symbol)
        if stock == None:
            flash("Please select a stock to sell", "danger                                                                                                                                                                                                                                                                                                                                                                                                   ")
            return render_template("sell.html", stocks=stocks)

        shares = int(request.form.get("shares"))

        if stock[0]["shares"] == 0:
            flash("You do not own any shares of this stock", "danger")
            return render_template("sell.html", stocks=stocks)

        if not shares > 0:
            flash("Please enter a valid number of shares", "danger")
            return render_template("sell.html", stocks=stocks)

        if shares > stock[0]["shares"]:
            flash("You do not have enough shares", "danger")
            return render_template("sell.html", stocks=stocks)

        """Update database"""
        info = lookup(symbol)
        db.execute("INSERT INTO stock_info (user_id, symbol, name, shares, price) VALUES (:id, :symbol, :name, :shares, :price)"
                    , id = session["user_id"]
                    , symbol = symbol
                    , name=info["name"]
                    , shares=(-1*shares)
                    , price=info["price"])

        total = stock[0]["total_bought"] - (stock[0]["avg"]*shares)
        shares_update = stock[0]["shares"] - shares

        if shares_update == 0:
            db.execute("DELETE FROM :name WHERE symbol=:symbol"
                        , name = table_name(session["user_id"])
                        , symbol=symbol)
        else:
            db.execute("UPDATE :name SET shares=:shares, avg=:avg, total_bought=:total WHERE symbol=:symbol"
                        , name = table_name(session["user_id"])
                        , shares = shares_update
                        , avg = total/float(shares_update)
                        , total = total
                        , symbol=symbol)

        db.execute("UPDATE users SET cash=cash + ? WHERE id= ?"
                    , info["price"]*shares
                    , session["user_id"])

        flash(f"Sold {shares} shares of {symbol}", "success")

        # Return to homepage
        return redirect("/")
    else:
        return render_template("sell.html", stocks=stocks)


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    transactions = db.execute("SELECT * FROM stock_info WHERE user_id=:id ORDER BY time DESC", id=session["user_id"])
    return render_template("history.html", transactions=transactions)

@app.route("/leaderboard")
@login_required
def leaderboard():
    """Show the leaderboard of all the users ranking them by total money"""
    users = db.execute("SELECT id, username, cash FROM users")
    for user in users:
        stock_value = 0
        stocks = db.execute("SELECT * FROM :name", name=table_name(user["id"]))
        for stock in stocks:
            stock_value = lookup(stock["symbol"])["price"] * stock["shares"]
        user["money"] = user["cash"] + stock_value
    users = sorted(users, key=itemgetter("money"), reverse=True)

    flash(f"Your rank is {[user['id'] for user in users].index(session['user_id']) + 1}", "success")
    return render_template("leaderboard.html", users=users)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            flash("username field must not be left blank", "danger")
            return render_template("login.html")

        # Ensure password was submitted
        elif not request.form.get("password"):
            flash("password field must not be left blank", "danger")
            return render_template("login.html")

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            flash("Incorrect username or password", "danger")
            return render_template("login.html")

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    session.clear()

    if request.method == "POST":

        """Validation"""
        # Ensure username was submitted
        if not request.form.get("username"):
            flash("username field must not be left empty", "danger")
            return render_template("register.html")

        # Ensure password was submitted
        elif not request.form.get("password"):
            flash("password field must not be left empty", "danger")
            return render_template("register.html")

        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))
        if len(rows) != 0:
            flash("username not available", "danger")
            return render_template("register.html")

        if request.form.get("confirmation") != request.form.get("password"):
            flash("passwords do not match", "danger")
            return render_template("register.html")


        """Initialising the user"""
        # Create a new user in the users table
        session["user_id"] = db.execute("INSERT INTO users (username, hash) VALUES (:username, :pwd)",
                    username=request.form.get("username"), pwd=generate_password_hash(request.form.get("password")))

        # Create a new table to store user's stock data
        db.execute("CREATE TABLE IF NOT EXISTS :name (symbol TEXT NOT NULL UNIQUE, shares INTEGER, avg NUMERIC, total_bought NUMERIC)", name=table_name(session["user_id"]))

        flash("Successfully created new user", "success")

        # Redirect user to home page
        return redirect("/")
    else:
        return render_template("register.html")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
