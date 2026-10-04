try:
    a=int(input("Enter a number: "))
    b=int(input("Enter another number: "))
    print(f"The sum of the numbers is: {a + b}")
except ValueError:
    print("Hiba: Érvénytelen számot adtál meg.")
print("A program véget ért.")